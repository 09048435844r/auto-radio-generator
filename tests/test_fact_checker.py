"""FactChecker / FactCheckReport regression tests

Scope (unit-level, no real LLM calls):
  1. FactCheckReport / FactCheckIssue round-trip and accessors
  2. FactChecker._parse_report_response handles valid / malformed JSON
  3. FactChecker._extract_script_text concatenates dialogue only (skips actions)
  4. FactChecker.check raises on empty inputs (validation)
  5. FactChecker.check fail-fast on finish_reason="length"
  6. SessionManager save/load/has fact_check_report round-trip
  7. _format_factcheck_markdown UI helper (color bands, missing file)
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models.fact_check_report import (
    FactCheckIssue,
    FactCheckReport,
)
from core.models.script import Script, DialogueTurn, TurnType, ActionType


# ---------------------------------------------------------------------------
# FactCheckReport / FactCheckIssue data model tests
# ---------------------------------------------------------------------------

def _make_sample_report() -> FactCheckReport:
    return FactCheckReport(
        overall_confidence=72,
        issues=[
            FactCheckIssue(
                severity="high",
                script_quote="ずんだもん「9 割の患者が改善したのだ！」",
                issue="リサーチには『70%が改善』とあるが台本では『9 割』と誇張",
                suggestion="『9 割』→『約 70%』に修正、出典を明記",
            ),
            FactCheckIssue(
                severity="medium",
                script_quote="めたん「最新の研究では…」",
                issue="『最新の研究』が具体的にどの研究か不明",
                suggestion="研究名（年・主体）を追記",
            ),
            FactCheckIssue(
                severity="low",
                script_quote="ずんだもん「めっちゃすごいのだ」",
                issue="主観的表現、補足推奨",
                suggestion="具体的な数値を添えるとより伝わる",
            ),
        ],
        summary="数値の誇張 1 件と出典曖昧が 1 件検出された。修正後は 90 程度に回復可能。",
    )


def test_fact_check_report_confidence_band_green():
    r = FactCheckReport(overall_confidence=85, summary="")
    assert r.confidence_band() == "green"


def test_fact_check_report_confidence_band_yellow():
    r = FactCheckReport(overall_confidence=70, summary="")
    assert r.confidence_band() == "yellow"


def test_fact_check_report_confidence_band_red():
    r = FactCheckReport(overall_confidence=40, summary="")
    assert r.confidence_band() == "red"


def test_fact_check_report_confidence_band_boundary_80():
    """80 はちょうど green の下限"""
    assert FactCheckReport(overall_confidence=80, summary="").confidence_band() == "green"
    assert FactCheckReport(overall_confidence=79, summary="").confidence_band() == "yellow"


def test_fact_check_report_confidence_band_boundary_60():
    """60 はちょうど yellow の下限"""
    assert FactCheckReport(overall_confidence=60, summary="").confidence_band() == "yellow"
    assert FactCheckReport(overall_confidence=59, summary="").confidence_band() == "red"


def test_fact_check_report_issues_by_severity_filters():
    r = _make_sample_report()
    assert len(r.issues_by_severity("high")) == 1
    assert len(r.issues_by_severity("medium")) == 1
    assert len(r.issues_by_severity("low")) == 1


def test_fact_check_report_has_critical_issues():
    r = _make_sample_report()
    assert r.has_critical_issues() is True
    no_high = FactCheckReport(
        overall_confidence=90,
        issues=[FactCheckIssue(
            severity="low", script_quote="x", issue="y", suggestion="z",
        )],
        summary="",
    )
    assert no_high.has_critical_issues() is False


def test_fact_check_report_roundtrip_json():
    r = _make_sample_report()
    blob = r.model_dump_json()
    restored = FactCheckReport.model_validate_json(blob)
    assert restored.overall_confidence == 72
    assert len(restored.issues) == 3
    assert restored.issues[0].severity == "high"


def test_fact_check_report_confidence_validation():
    """overall_confidence must be 0-100"""
    with pytest.raises(Exception):
        FactCheckReport(overall_confidence=101, summary="")
    with pytest.raises(Exception):
        FactCheckReport(overall_confidence=-1, summary="")


# ---------------------------------------------------------------------------
# FactChecker._parse_report_response
# ---------------------------------------------------------------------------

def _make_fact_checker_for_parse(mock_app_config):
    """Build a FactChecker instance without touching the LLM port."""
    from services.script_generation.fact_checker import FactChecker

    mock_port = MagicMock()
    mock_port.provider_name = "gemini"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.fact_checker = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.max_tokens = 8192
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.min_confidence_warning = 60
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.script_char_limit = 8000
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.research_char_limit = 8000

    return FactChecker(mock_port, mock_app_config)


def test_parse_valid_json(mock_app_config):
    checker = _make_fact_checker_for_parse(mock_app_config)
    payload = json.dumps({
        "overall_confidence": 78,
        "summary": "全体的にリサーチに準拠している。",
        "issues": [
            {
                "severity": "high",
                "script_quote": "9 割の患者が改善",
                "issue": "リサーチには 70% とある",
                "suggestion": "70% に修正",
            }
        ],
    })
    report = checker._parse_report_response(payload)
    assert report.overall_confidence == 78
    assert len(report.issues) == 1
    assert report.issues[0].severity == "high"


def test_parse_clamps_confidence_to_range(mock_app_config):
    checker = _make_fact_checker_for_parse(mock_app_config)
    high = checker._parse_report_response(
        json.dumps({"overall_confidence": 250, "issues": [], "summary": ""})
    )
    assert high.overall_confidence == 100
    low = checker._parse_report_response(
        json.dumps({"overall_confidence": -50, "issues": [], "summary": ""})
    )
    assert low.overall_confidence == 0


def test_parse_normalizes_unknown_severity_to_medium(mock_app_config):
    checker = _make_fact_checker_for_parse(mock_app_config)
    payload = json.dumps({
        "overall_confidence": 70,
        "summary": "",
        "issues": [
            {
                "severity": "critical",  # not in SSOT
                "script_quote": "quote",
                "issue": "issue text",
                "suggestion": "fix",
            }
        ],
    })
    report = checker._parse_report_response(payload)
    assert len(report.issues) == 1
    assert report.issues[0].severity == "medium"  # fallback


def test_parse_skips_issues_with_empty_required_fields(mock_app_config):
    checker = _make_fact_checker_for_parse(mock_app_config)
    payload = json.dumps({
        "overall_confidence": 70,
        "summary": "",
        "issues": [
            # Valid
            {"severity": "high", "script_quote": "q", "issue": "i", "suggestion": "s"},
            # Empty script_quote → skipped
            {"severity": "medium", "script_quote": "", "issue": "i", "suggestion": "s"},
            # Empty issue → skipped
            {"severity": "low", "script_quote": "q", "issue": "", "suggestion": "s"},
            # Non-dict → skipped
            "not a dict",
        ],
    })
    report = checker._parse_report_response(payload)
    assert len(report.issues) == 1
    assert report.issues[0].severity == "high"


def test_parse_sorts_issues_by_severity(mock_app_config):
    checker = _make_fact_checker_for_parse(mock_app_config)
    payload = json.dumps({
        "overall_confidence": 70,
        "summary": "",
        "issues": [
            {"severity": "low", "script_quote": "q1", "issue": "i1", "suggestion": "s1"},
            {"severity": "high", "script_quote": "q2", "issue": "i2", "suggestion": "s2"},
            {"severity": "medium", "script_quote": "q3", "issue": "i3", "suggestion": "s3"},
        ],
    })
    report = checker._parse_report_response(payload)
    assert [i.severity for i in report.issues] == ["high", "medium", "low"]


def test_parse_recovers_from_codeblock_wrapper(mock_app_config):
    """LLM が ```json ブロックに包んでも sanitize で復元できること"""
    checker = _make_fact_checker_for_parse(mock_app_config)
    payload = (
        "```json\n"
        '{"overall_confidence": 90, "issues": [], "summary": "no issues"}\n'
        "```"
    )
    report = checker._parse_report_response(payload)
    assert report.overall_confidence == 90
    assert report.summary == "no issues"


# ---------------------------------------------------------------------------
# FactChecker._extract_script_text
# ---------------------------------------------------------------------------

def _make_minimal_script(turns: list[DialogueTurn]) -> Script:
    """Create a Script with the bare minimum fields (sections min_length=10)."""
    # Pad with dialogue turns to satisfy min_length=10
    padded = list(turns)
    while len(padded) < 10:
        padded.append(DialogueTurn(speaker="A", text="padding", turn_type=TurnType.DIALOGUE))
    return Script(
        title="test title",
        thumbnail_title="test thumb",
        sections=padded,
    )


def test_extract_script_text_concatenates_dialogue():
    from services.script_generation.fact_checker import FactChecker

    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="こんにちは", turn_type=TurnType.DIALOGUE),
        DialogueTurn(speaker="B", text="今日のテーマは亜麻仁油です", turn_type=TurnType.DIALOGUE),
    ])
    text = FactChecker._extract_script_text(script)
    assert "A: こんにちは" in text
    assert "B: 今日のテーマは亜麻仁油です" in text


def test_extract_script_text_skips_actions():
    from services.script_generation.fact_checker import FactChecker

    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="セリフ1", turn_type=TurnType.DIALOGUE),
        DialogueTurn(
            speaker=None,
            text=None,
            turn_type=TurnType.ACTION,
            action_type=ActionType.JINGLE,
            action_path="x.mp3",
        ),
        DialogueTurn(speaker="B", text="セリフ2", turn_type=TurnType.DIALOGUE),
    ])
    text = FactChecker._extract_script_text(script)
    assert "セリフ1" in text
    assert "セリフ2" in text
    assert "x.mp3" not in text  # action skipped


def test_extract_script_text_skips_empty_text():
    from services.script_generation.fact_checker import FactChecker

    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="有効なセリフ", turn_type=TurnType.DIALOGUE),
        DialogueTurn(speaker="B", text="   ", turn_type=TurnType.DIALOGUE),  # whitespace only
        DialogueTurn(speaker="A", text="", turn_type=TurnType.DIALOGUE),
    ])
    text = FactChecker._extract_script_text(script)
    assert "有効なセリフ" in text
    # Whitespace-only and empty text should be skipped
    lines = [line for line in text.split("\n") if line.strip()]
    # Account for the padded turns added by _make_minimal_script ("padding" * N)
    non_padding = [line for line in lines if "padding" not in line]
    assert len(non_padding) == 1


# ---------------------------------------------------------------------------
# FactChecker.check (validation paths)
# ---------------------------------------------------------------------------

def test_check_raises_on_empty_research(mock_app_config):
    checker = _make_fact_checker_for_parse(mock_app_config)
    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="hi", turn_type=TurnType.DIALOGUE),
    ])
    research = MagicMock()
    research.content = ""

    with pytest.raises(ValueError, match="research_data has no content"):
        asyncio.run(checker.check(theme="t", script=script, research_data=research))


def test_check_raises_on_empty_script(mock_app_config):
    checker = _make_fact_checker_for_parse(mock_app_config)
    # All turns are actions (no dialogue text)
    script = _make_minimal_script([
        DialogueTurn(
            speaker=None, text=None,
            turn_type=TurnType.ACTION,
            action_type=ActionType.JINGLE,
            action_path="x.mp3",
        ),
    ])
    # Override padded dialogue turns to all be empty so _extract_script_text returns ""
    for turn in script.sections:
        if turn.turn_type == TurnType.DIALOGUE:
            turn.text = ""
    research = MagicMock()
    research.content = "research content"

    with pytest.raises(ValueError, match="script has no dialogue text"):
        asyncio.run(checker.check(theme="t", script=script, research_data=research))


def test_check_fail_fast_on_length_truncation(mock_app_config):
    """finish_reason='length' should raise RuntimeError (fail-fast contract)"""
    from services.script_generation.fact_checker import FactChecker
    from core.interfaces.llm_port import LLMResponse
    from core.models import LLMUsage

    mock_port = MagicMock()
    mock_port.provider_name = "gemini"
    truncated_response = LLMResponse(
        content="{partial",
        usage=LLMUsage(
            provider="gemini",
            model_name="gemini-2.5-flash",
            input_tokens=100,
            output_tokens=8192,
        ),
        finish_reason="length",
    )
    mock_port.generate = AsyncMock(return_value=truncated_response)

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.fact_checker = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.max_tokens = 8192
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.min_confidence_warning = 60
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.script_char_limit = 8000
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.research_char_limit = 8000

    checker = FactChecker(mock_port, mock_app_config)
    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="セリフ", turn_type=TurnType.DIALOGUE),
    ])
    research = MagicMock()
    research.content = "research content"

    with pytest.raises(RuntimeError, match="truncated"):
        asyncio.run(checker.check(theme="t", script=script, research_data=research))


# ---------------------------------------------------------------------------
# SessionManager FactCheckReport persistence
# ---------------------------------------------------------------------------

def test_session_manager_save_load_fact_check_report(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="test_sess")
    report = _make_sample_report()

    assert sm.has_fact_check_report() is False
    saved_path = sm.save_fact_check_report(report)
    assert saved_path.exists()
    assert sm.has_fact_check_report() is True

    loaded = sm.load_fact_check_report()
    assert loaded.overall_confidence == 72
    assert len(loaded.issues) == 3
    assert loaded.issues[0].severity == "high"


def test_session_manager_load_missing_fact_check_report(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="test_sess")
    with pytest.raises(FileNotFoundError):
        sm.load_fact_check_report()


# ---------------------------------------------------------------------------
# _format_factcheck_markdown (UI helper)
# ---------------------------------------------------------------------------

def test_format_factcheck_markdown_returns_placeholder_for_none():
    from app import _format_factcheck_markdown, _FACTCHECK_PLACEHOLDER

    assert _format_factcheck_markdown(None) == _FACTCHECK_PLACEHOLDER
    assert _format_factcheck_markdown("") == _FACTCHECK_PLACEHOLDER


def test_format_factcheck_markdown_handles_missing_file(tmp_path: Path):
    from app import _format_factcheck_markdown

    # tmp_path exists but has no factcheck_report.json
    md = _format_factcheck_markdown(tmp_path)
    assert "実行されていません" in md or "ファクトチェック" in md


def test_format_factcheck_markdown_renders_green_band(tmp_path: Path):
    from app import _format_factcheck_markdown

    report = FactCheckReport(
        overall_confidence=92,
        issues=[],
        summary="重大な問題は検出されませんでした",
    )
    (tmp_path / "factcheck_report.json").write_text(
        report.model_dump_json(), encoding="utf-8"
    )
    md = _format_factcheck_markdown(tmp_path)
    assert "🟢" in md
    assert "92/100" in md
    assert "重大な問題は検出されませんでした" in md


def test_format_factcheck_markdown_renders_red_band_with_issues(tmp_path: Path):
    from app import _format_factcheck_markdown

    report = _make_sample_report()
    # Force red band
    report = report.model_copy(update={"overall_confidence": 35})
    (tmp_path / "factcheck_report.json").write_text(
        report.model_dump_json(), encoding="utf-8"
    )
    md = _format_factcheck_markdown(tmp_path)
    assert "🔴" in md
    assert "35/100" in md
    # Issues are rendered
    assert "9 割" in md  # script_quote
    assert "誇張" in md  # issue text


def test_format_factcheck_markdown_handles_corrupt_json(tmp_path: Path):
    from app import _format_factcheck_markdown

    (tmp_path / "factcheck_report.json").write_text("not valid json", encoding="utf-8")
    md = _format_factcheck_markdown(tmp_path)
    assert "読み込みエラー" in md or "エラー" in md


# ===========================================================================
# Phase 3A: FactFixAgent / apply_fixes_to_script / FactCheckIssue extension
# ===========================================================================

def test_fact_check_issue_extension_defaults():
    """新フィールド fixed_text / auto_fixed のデフォルト値"""
    issue = FactCheckIssue(
        severity="high", script_quote="q", issue="i", suggestion="s",
    )
    assert issue.fixed_text is None
    assert issue.auto_fixed is False


def test_fact_check_issue_roundtrip_with_extension():
    """fixed_text / auto_fixed が JSON 往復を耐える"""
    issue = FactCheckIssue(
        severity="medium",
        script_quote="9 割の患者",
        issue="リサーチでは 70%",
        suggestion="70% に修正",
        fixed_text="約 70% の患者",
        auto_fixed=True,
    )
    blob = issue.model_dump_json()
    restored = FactCheckIssue.model_validate_json(blob)
    assert restored.fixed_text == "約 70% の患者"
    assert restored.auto_fixed is True


def _make_fact_fixer(mock_app_config):
    """Build a FactFixAgent without touching the LLM port (returns instance + mock_port)."""
    from services.script_generation.fact_checker import FactFixAgent

    mock_port = MagicMock()
    mock_port.provider_name = "gemini"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.fact_checker = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_checker.auto_fix_max_tokens = 1024

    return FactFixAgent(mock_port, mock_app_config), mock_port


def test_fact_fixer_parse_response_valid():
    from services.script_generation.fact_checker import FactFixAgent

    res = FactFixAgent._parse_fix_response('{"fixed_text": "約 70% の患者が改善"}')
    assert res == "約 70% の患者が改善"


def test_fact_fixer_parse_response_handles_codeblock():
    from services.script_generation.fact_checker import FactFixAgent

    payload = "```json\n" + '{"fixed_text": "修正後テキスト"}' + "\n```"
    assert FactFixAgent._parse_fix_response(payload) == "修正後テキスト"


def test_fact_fixer_parse_response_returns_none_on_invalid():
    from services.script_generation.fact_checker import FactFixAgent

    assert FactFixAgent._parse_fix_response("garbage") is None
    assert FactFixAgent._parse_fix_response('{"other_key": "x"}') is None
    # empty string after strip
    assert FactFixAgent._parse_fix_response('{"fixed_text": "   "}') is None


def test_fact_fixer_skips_low_severity(mock_app_config):
    """low severity issues は修正対象外。fix_report で auto_fixed=False のまま"""
    from core.interfaces.llm_port import LLMResponse
    from core.models import LLMUsage

    fixer, mock_port = _make_fact_fixer(mock_app_config)
    # generate は呼ばれてはいけないが、防御的に有効レスポンスを返す設定
    mock_port.generate = AsyncMock(return_value=LLMResponse(
        content='{"fixed_text": "should not be used"}',
        usage=LLMUsage(provider="gemini", model_name="x", input_tokens=1, output_tokens=1),
        finish_reason="stop",
    ))

    report = FactCheckReport(
        overall_confidence=85,
        issues=[
            FactCheckIssue(severity="low", script_quote="q", issue="i", suggestion="s"),
        ],
        summary="",
    )
    result = asyncio.run(fixer.fix_report(report))

    assert result.issues[0].auto_fixed is False
    assert result.issues[0].fixed_text is None
    assert fixer.last_fixed_count == 0
    assert fixer.last_skipped_count == 1
    mock_port.generate.assert_not_called()


def test_fact_fixer_fixes_high_and_medium(mock_app_config):
    """high/medium issues が LLM 呼び出しで修正されること"""
    from core.interfaces.llm_port import LLMResponse
    from core.models import LLMUsage

    fixer, mock_port = _make_fact_fixer(mock_app_config)
    mock_port.generate = AsyncMock(return_value=LLMResponse(
        content='{"fixed_text": "修正後テキスト"}',
        usage=LLMUsage(provider="gemini", model_name="x", input_tokens=10, output_tokens=5),
        finish_reason="stop",
    ))

    report = FactCheckReport(
        overall_confidence=60,
        issues=[
            FactCheckIssue(severity="high", script_quote="原文 high", issue="i1", suggestion="s1"),
            FactCheckIssue(severity="medium", script_quote="原文 med", issue="i2", suggestion="s2"),
            FactCheckIssue(severity="low", script_quote="原文 low", issue="i3", suggestion="s3"),
        ],
        summary="",
    )
    result = asyncio.run(fixer.fix_report(report))

    # high / medium は修正、low はスキップ
    assert result.issues[0].auto_fixed is True
    assert result.issues[0].fixed_text == "修正後テキスト"
    assert result.issues[1].auto_fixed is True
    assert result.issues[1].fixed_text == "修正後テキスト"
    assert result.issues[2].auto_fixed is False
    assert result.issues[2].fixed_text is None
    assert fixer.last_fixed_count == 2
    assert fixer.last_skipped_count == 1
    assert mock_port.generate.await_count == 2


def test_fact_fixer_partial_failure_does_not_break_loop(mock_app_config):
    """1 件の修正失敗が他の issues 修正を止めないこと"""
    from core.interfaces.llm_port import LLMResponse
    from core.models import LLMUsage

    fixer, mock_port = _make_fact_fixer(mock_app_config)

    async def flaky_generate(_request):
        # 1 回目は例外、2 回目は成功
        if mock_port.generate.await_count == 1:
            raise RuntimeError("provider blip")
        return LLMResponse(
            content='{"fixed_text": "ok"}',
            usage=LLMUsage(provider="gemini", model_name="x", input_tokens=1, output_tokens=1),
            finish_reason="stop",
        )
    mock_port.generate = AsyncMock(side_effect=flaky_generate)

    report = FactCheckReport(
        overall_confidence=50,
        issues=[
            FactCheckIssue(severity="high", script_quote="q1", issue="i1", suggestion="s1"),
            FactCheckIssue(severity="medium", script_quote="q2", issue="i2", suggestion="s2"),
        ],
        summary="",
    )
    result = asyncio.run(fixer.fix_report(report))

    # 1 件目失敗、2 件目成功
    assert result.issues[0].auto_fixed is False
    assert result.issues[1].auto_fixed is True
    assert fixer.last_fixed_count == 1
    assert fixer.last_failed_count == 1


def test_fact_fixer_fail_fast_on_length_truncation(mock_app_config):
    """finish_reason='length' は RuntimeError → 該当 issue は failed としてカウントされる"""
    from core.interfaces.llm_port import LLMResponse
    from core.models import LLMUsage

    fixer, mock_port = _make_fact_fixer(mock_app_config)
    mock_port.generate = AsyncMock(return_value=LLMResponse(
        content='{"fixed_t',
        usage=LLMUsage(provider="gemini", model_name="x", input_tokens=10, output_tokens=1024),
        finish_reason="length",
    ))

    report = FactCheckReport(
        overall_confidence=50,
        issues=[
            FactCheckIssue(severity="high", script_quote="q", issue="i", suggestion="s"),
        ],
        summary="",
    )
    result = asyncio.run(fixer.fix_report(report))
    assert result.issues[0].auto_fixed is False
    assert fixer.last_failed_count == 1


def test_fact_fixer_no_targets():
    """high/medium issue が 0 件なら LLM を呼ばずに完走"""
    # Use ad-hoc app config without mock fixture to keep test isolated
    pass  # covered by test_fact_fixer_skips_low_severity


# ---------------------------------------------------------------------------
# apply_fixes_to_script
# ---------------------------------------------------------------------------

def test_apply_fixes_to_script_replaces_matched_quote():
    from services.script_generation.fact_checker import apply_fixes_to_script

    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="9 割の患者が改善した", turn_type=TurnType.DIALOGUE),
        DialogueTurn(speaker="B", text="本当ですか？", turn_type=TurnType.DIALOGUE),
    ])
    report = FactCheckReport(
        overall_confidence=60,
        issues=[
            FactCheckIssue(
                severity="high",
                script_quote="9 割の患者が改善した",
                issue="誇張",
                suggestion="70% に修正",
                fixed_text="約 70% の患者が改善した",
                auto_fixed=True,
            ),
        ],
        summary="",
    )

    fixed_script, applied = apply_fixes_to_script(script, report)

    assert applied == 1
    assert fixed_script.sections[0].text == "約 70% の患者が改善した"
    # Original script should be untouched
    assert script.sections[0].text == "9 割の患者が改善した"


def test_apply_fixes_to_script_handles_speaker_prefix():
    """script_quote に話者プレフィックスがある場合（A: ... 形式）も適用できる"""
    from services.script_generation.fact_checker import apply_fixes_to_script

    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="9 割の患者が改善したのだ！", turn_type=TurnType.DIALOGUE),
    ])
    report = FactCheckReport(
        overall_confidence=60,
        issues=[
            FactCheckIssue(
                severity="high",
                script_quote="A: 9 割の患者が改善したのだ！",
                issue="誇張",
                suggestion="70% へ",
                fixed_text="A: 約 70% の患者が改善したのだ！",
                auto_fixed=True,
            ),
        ],
        summary="",
    )
    fixed_script, applied = apply_fixes_to_script(script, report)
    assert applied == 1
    assert "約 70%" in fixed_script.sections[0].text
    assert "9 割" not in fixed_script.sections[0].text


def test_apply_fixes_to_script_skips_unmatched_quote():
    """script_quote がどのターンにもマッチしない場合は skip（ログ警告のみ）"""
    from services.script_generation.fact_checker import apply_fixes_to_script

    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="全く別のセリフ", turn_type=TurnType.DIALOGUE),
    ])
    report = FactCheckReport(
        overall_confidence=60,
        issues=[
            FactCheckIssue(
                severity="high",
                script_quote="存在しない引用",
                issue="x",
                suggestion="y",
                fixed_text="zzzzz",
                auto_fixed=True,
            ),
        ],
        summary="",
    )
    fixed_script, applied = apply_fixes_to_script(script, report)
    assert applied == 0
    # Original text retained (script_fixed.json は original の写し)
    assert fixed_script.sections[0].text == "全く別のセリフ"


def test_apply_fixes_to_script_skips_non_auto_fixed():
    """auto_fixed=False の issue は適用対象外"""
    from services.script_generation.fact_checker import apply_fixes_to_script

    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="原文を残すべき", turn_type=TurnType.DIALOGUE),
    ])
    report = FactCheckReport(
        overall_confidence=60,
        issues=[
            FactCheckIssue(
                severity="high",
                script_quote="原文を残すべき",
                issue="x",
                suggestion="y",
                # fixed_text/auto_fixed not set
            ),
        ],
        summary="",
    )
    fixed_script, applied = apply_fixes_to_script(script, report)
    assert applied == 0
    assert fixed_script.sections[0].text == "原文を残すべき"


# ---------------------------------------------------------------------------
# SessionManager: script_fixed.json
# ---------------------------------------------------------------------------

def test_session_manager_save_load_script_fixed(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="sess_3a")
    script = _make_minimal_script([
        DialogueTurn(speaker="A", text="修正後テキスト", turn_type=TurnType.DIALOGUE),
    ])

    assert sm.has_script_fixed() is False
    saved_path = sm.save_script_fixed(script)
    assert saved_path.exists()
    assert saved_path.name == "script_fixed.json"
    assert sm.has_script_fixed() is True

    loaded = sm.load_script_fixed()
    assert any(t.text == "修正後テキスト" for t in loaded.sections)


def test_session_manager_load_missing_script_fixed_raises(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="sess_3a_missing")
    with pytest.raises(FileNotFoundError):
        sm.load_script_fixed()


# ---------------------------------------------------------------------------
# Phase 3B: UI markdown — before/after rendering
# ---------------------------------------------------------------------------

def test_format_factcheck_markdown_renders_before_after_for_fixed_issue(tmp_path: Path):
    """auto_fixed=True の issue は『修正前』『修正後』表示になる"""
    from app import _format_factcheck_markdown

    report = FactCheckReport(
        overall_confidence=70,
        issues=[
            FactCheckIssue(
                severity="high",
                script_quote="9 割の患者が改善",
                issue="誇張",
                suggestion="70% に修正",
                fixed_text="約 70% の患者が改善",
                auto_fixed=True,
            ),
        ],
        summary="",
    )
    (tmp_path / "factcheck_report.json").write_text(
        report.model_dump_json(), encoding="utf-8"
    )
    md = _format_factcheck_markdown(tmp_path)

    assert "修正済み" in md
    assert "修正前" in md
    assert "修正後" in md
    assert "9 割の患者が改善" in md
    assert "約 70% の患者が改善" in md
    # 自動修正 N 件 表示
    assert "自動修正" in md
    assert "1件" in md


def test_format_factcheck_markdown_keeps_legacy_for_non_fixed_issue(tmp_path: Path):
    """auto_fixed=False の issue は従来通り『問題点 + 修正案』表示"""
    from app import _format_factcheck_markdown

    report = FactCheckReport(
        overall_confidence=70,
        issues=[
            FactCheckIssue(
                severity="medium",
                script_quote="原文",
                issue="出典不明",
                suggestion="出典を追記",
                # auto_fixed defaults False
            ),
        ],
        summary="",
    )
    (tmp_path / "factcheck_report.json").write_text(
        report.model_dump_json(), encoding="utf-8"
    )
    md = _format_factcheck_markdown(tmp_path)

    assert "該当箇所" in md
    assert "修正案" in md
    assert "修正済み" not in md
    assert "修正前" not in md
    assert "修正後" not in md


def test_format_factcheck_markdown_mixed_fixed_and_unfixed(tmp_path: Path):
    """修正済み + 未修正の混在ケース"""
    from app import _format_factcheck_markdown

    report = FactCheckReport(
        overall_confidence=65,
        issues=[
            FactCheckIssue(
                severity="high",
                script_quote="数値誇張原文",
                issue="誇張",
                suggestion="数値を修正",
                fixed_text="正しい数値",
                auto_fixed=True,
            ),
            FactCheckIssue(
                severity="low",
                script_quote="軽微な脚色",
                issue="補足推奨",
                suggestion="出典追加",
                # auto_fixed False (low はスキップ済み)
            ),
        ],
        summary="",
    )
    (tmp_path / "factcheck_report.json").write_text(
        report.model_dump_json(), encoding="utf-8"
    )
    md = _format_factcheck_markdown(tmp_path)

    assert "修正済み" in md
    assert "修正前" in md
    assert "修正後" in md
    assert "正しい数値" in md
    # 軽微なほうは従来表示
    assert "該当箇所" in md
    assert "軽微な脚色" in md
