"""FactExtractor / FactSheet regression tests (Phase 4 施策③)

Scope (unit-level, no real LLM calls):
  1. FactSheet / ExtractedFact round-trip and accessors
  2. FactExtractor._parse_fact_sheet_response handles valid and malformed JSON
  3. TopicCurator._build_curation_user_prompt injects FactSheet defensively
     (including the None case for backward compat)
  4. SessionManager save/load/has FactSheet round-trips
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.models.fact_sheet import ExtractedFact, FactSheet


# ---------------------------------------------------------------------------
# FactSheet data model tests
# ---------------------------------------------------------------------------

def _make_sample_fact_sheet() -> FactSheet:
    return FactSheet(
        facts=[
            ExtractedFact(
                statement="OpenAI は 2024 年に売上 1200 万ドルから 37 億ドルへ拡大した",
                category="数値",
                numeric_value="37億ドル",
                entity="OpenAI",
                source_citation=None,
                surprise_score=9,
            ),
            ExtractedFact(
                statement="日銀は 2024 年 3 月にマイナス金利を解除した",
                category="事件",
                numeric_value="2024年3月",
                entity="日銀",
                source_citation=None,
                surprise_score=7,
            ),
            ExtractedFact(
                statement="ずんだもんは東北ずん子プロジェクトの公式マスコットである",
                category="その他",
                numeric_value=None,
                entity="ずんだもん",
                source_citation=None,
                surprise_score=3,
            ),
        ],
        theme_summary="AI 業界の急成長と金融政策の転換点に関するリサーチ",
        extractor_reasoning="数値・固有名詞が明確なファクトを優先的に抽出した",
    )


def test_fact_sheet_top_facts_sorts_by_surprise_score():
    sheet = _make_sample_fact_sheet()
    top = sheet.top_facts(limit=2)
    assert len(top) == 2
    # 最高スコア（9）が先頭
    assert top[0].surprise_score == 9
    assert top[1].surprise_score == 7


def test_fact_sheet_top_facts_respects_limit():
    sheet = _make_sample_fact_sheet()
    assert len(sheet.top_facts(limit=1)) == 1
    assert len(sheet.top_facts(limit=10)) == 3  # facts 3件しかないので頭打ち


def test_fact_sheet_is_empty():
    empty = FactSheet()
    assert empty.is_empty() is True

    not_empty = _make_sample_fact_sheet()
    assert not_empty.is_empty() is False


def test_fact_sheet_roundtrip_json():
    """FactSheet must serialize and deserialize without loss."""
    sheet = _make_sample_fact_sheet()
    blob = sheet.model_dump_json()
    restored = FactSheet.model_validate_json(blob)
    assert len(restored.facts) == 3
    assert restored.facts[0].statement == sheet.facts[0].statement
    assert restored.facts[0].surprise_score == 9
    assert restored.theme_summary == sheet.theme_summary


def test_extracted_fact_surprise_score_validation():
    """surprise_score must be 1-10 (Pydantic Field constraint)."""
    with pytest.raises(Exception):
        ExtractedFact(statement="test", surprise_score=11)
    with pytest.raises(Exception):
        ExtractedFact(statement="test", surprise_score=0)


# ---------------------------------------------------------------------------
# FactExtractor._parse_fact_sheet_response
# ---------------------------------------------------------------------------

def _make_fact_extractor_for_parse(mock_app_config):
    """Build a FactExtractor instance without touching the LLM port."""
    from services.script_generation.fact_extractor import FactExtractor

    mock_port = MagicMock()
    mock_port.provider_name = "gemini"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_facts = 30

    return FactExtractor(mock_port, mock_app_config)


def test_parse_valid_json(mock_app_config):
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [
            {
                "statement": "OpenAI の売上は 37 億ドルに達した",
                "category": "数値",
                "numeric_value": "37億ドル",
                "entity": "OpenAI",
                "source_citation": None,
                "surprise_score": 9,
            },
            {
                "statement": "日銀がマイナス金利を解除",
                "category": "事件",
                "numeric_value": "2024年3月",
                "entity": "日銀",
                "source_citation": None,
                "surprise_score": 7,
            },
        ],
        "theme_summary": "テーマ要約",
        "extractor_reasoning": "理由",
    })
    sheet = extractor._parse_fact_sheet_response(raw)
    assert len(sheet.facts) == 2
    # surprise_score 降順でソート済み
    assert sheet.facts[0].surprise_score == 9
    assert sheet.facts[0].entity == "OpenAI"
    assert sheet.theme_summary == "テーマ要約"


def test_parse_skips_empty_statements(mock_app_config):
    """statement が空のファクトはスキップ（LLM がプレースホルダを出すケース対策）"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [
            {"statement": "", "surprise_score": 5},
            {"statement": "有効なファクト", "surprise_score": 6},
            {"statement": "   ", "surprise_score": 7},  # whitespace only
        ],
        "theme_summary": "",
    })
    sheet = extractor._parse_fact_sheet_response(raw)
    assert len(sheet.facts) == 1
    assert sheet.facts[0].statement == "有効なファクト"


def test_parse_clamps_surprise_score(mock_app_config):
    """surprise_score が範囲外でも 1〜10 に丸められてクラッシュしない"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [
            {"statement": "スコア過大", "surprise_score": 99},
            {"statement": "スコア過小", "surprise_score": -5},
            {"statement": "スコア不正", "surprise_score": "invalid"},
        ],
        "theme_summary": "",
    })
    sheet = extractor._parse_fact_sheet_response(raw)
    assert len(sheet.facts) == 3
    for fact in sheet.facts:
        assert 1 <= fact.surprise_score <= 10


def test_parse_normalizes_null_strings(mock_app_config):
    """'null' 文字列や空文字の numeric_value / entity は None に正規化される"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [
            {
                "statement": "テスト",
                "numeric_value": "null",
                "entity": "",
                "source_citation": "NULL",
                "surprise_score": 5,
            },
        ],
        "theme_summary": "",
    })
    sheet = extractor._parse_fact_sheet_response(raw)
    assert sheet.facts[0].numeric_value is None
    assert sheet.facts[0].entity is None
    assert sheet.facts[0].source_citation is None


def test_parse_handles_missing_facts_key(mock_app_config):
    """facts キーが欠けていても空リストで返す（エラーにしない）"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({"theme_summary": "サマリだけ"})
    sheet = extractor._parse_fact_sheet_response(raw)
    assert sheet.facts == []
    assert sheet.theme_summary == "サマリだけ"


# ---------------------------------------------------------------------------
# TopicCurator prompt injection
# ---------------------------------------------------------------------------

def _make_topic_curator(mock_app_config):
    from services.script_generation.topic_curator import TopicCurator

    mock_port = MagicMock()
    mock_port.provider_name = "gemini"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.max_topics = 3

    return TopicCurator(mock_port, mock_app_config)


def _make_research_result():
    # Lightweight stand-in for ResearchResult (dataclass)
    rd = MagicMock()
    rd.mode = "trivia"
    rd.content = "リサーチ生文字列（サンプル）"
    return rd


def test_curator_prompt_without_fact_sheet_is_backward_compatible(mock_app_config):
    """fact_sheet=None の場合、FactSheet セクションは追加されない（後方互換）"""
    curator = _make_topic_curator(mock_app_config)
    rd = _make_research_result()
    prompt = curator._build_curation_user_prompt(rd, target_count=3, fact_sheet=None)
    assert "構造化ファクトシート" not in prompt
    assert "FactExtractor による事前分析" not in prompt


def test_curator_prompt_injects_fact_sheet_when_provided(mock_app_config):
    curator = _make_topic_curator(mock_app_config)
    rd = _make_research_result()
    sheet = _make_sample_fact_sheet()
    prompt = curator._build_curation_user_prompt(rd, target_count=3, fact_sheet=sheet)
    # Section header must appear
    assert "構造化ファクトシート" in prompt
    assert "テーマ要約" in prompt
    # Top fact's entity and numeric_value must appear in the prompt
    assert "OpenAI" in prompt
    assert "37億ドル" in prompt
    # surprise_score metadata must be rendered
    assert "surprise=9" in prompt


def test_curator_prompt_skips_empty_fact_sheet(mock_app_config):
    """空の FactSheet（facts=[], theme_summary=''）が渡されても壊れない。セクションを出さない。"""
    curator = _make_topic_curator(mock_app_config)
    rd = _make_research_result()
    empty = FactSheet()
    prompt = curator._build_curation_user_prompt(rd, target_count=3, fact_sheet=empty)
    assert "構造化ファクトシート" not in prompt


# ---------------------------------------------------------------------------
# SessionManager save/load/has FactSheet
# ---------------------------------------------------------------------------

def test_session_manager_fact_sheet_roundtrip(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="fe_test")
    sm.session_dir.mkdir(parents=True, exist_ok=True)

    assert sm.has_fact_sheet() is False

    sheet = _make_sample_fact_sheet()
    saved = sm.save_fact_sheet(sheet)
    assert saved.exists()
    assert sm.has_fact_sheet() is True

    loaded = sm.load_fact_sheet()
    assert len(loaded.facts) == 3
    assert loaded.facts[0].entity == "OpenAI"
    assert loaded.theme_summary == sheet.theme_summary

    status = sm.get_session_status()
    assert status["fact_extraction_completed"] is True


def test_session_manager_load_fact_sheet_missing_raises(tmp_path: Path):
    from core.session_manager import SessionManager

    sm = SessionManager(project_root=tmp_path, session_id="empty_fe")
    sm.session_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        sm.load_fact_sheet()


# ---------------------------------------------------------------------------
# Phase 4 review #1: FactExtractorConfig defaults align with shipped config.yaml
# ---------------------------------------------------------------------------

def test_fact_extractor_config_defaults_are_enabled_and_carry_max_tokens():
    """FactExtractorConfig は enabled=True 既定、max_tokens が config 駆動可能。"""
    from core.models.config import FactExtractorConfig

    cfg = FactExtractorConfig()
    assert cfg.enabled is True, "SSOT: default enabled must match shipped config.yaml (true)"
    assert cfg.max_tokens == 8192
    assert cfg.max_facts == 30


# ---------------------------------------------------------------------------
# Phase 4 review #7: finish_reason=="length" must fail fast
# ---------------------------------------------------------------------------

class _FakeLLMResponse:
    """Minimal stand-in for LLMResponse with controllable finish_reason."""

    def __init__(self, content, usage, finish_reason):
        self.content = content
        self.usage = usage
        self.finish_reason = finish_reason


def test_extract_facts_raises_on_length_truncation(mock_app_config):
    """Phase 4 review #7: truncated LLM output must raise RuntimeError, not return partial JSON."""
    import asyncio
    from core.models.usage import LLMUsage

    extractor = _make_fact_extractor_for_parse(mock_app_config)

    fake_usage = LLMUsage(
        provider="gemini",
        model_name="test",
        input_tokens=10,
        output_tokens=10,
        request_count=1,
    )
    # Truncated JSON (intentionally malformed to prove we don't attempt to parse it)
    fake_response = _FakeLLMResponse(
        content='{"facts":[{"statement":"partial",',
        usage=fake_usage,
        finish_reason="length",
    )

    async def mock_generate(req):
        return fake_response

    extractor._llm.generate = mock_generate

    rd = _make_research_result()

    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(extractor.extract_facts(theme="test", research_data=rd))


def test_extract_facts_uses_config_max_tokens(mock_app_config):
    """Phase 4 review #7: max_tokens は config 駆動。request.max_tokens が設定値と一致する。"""
    import asyncio
    from core.models.usage import LLMUsage

    # Override max_tokens on the mocked config before constructing the extractor
    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_facts = 30
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_tokens = 16384

    from services.script_generation.fact_extractor import FactExtractor

    mock_port = MagicMock()
    mock_port.provider_name = "gemini"
    extractor = FactExtractor(mock_port, mock_app_config)

    assert extractor.max_tokens == 16384

    captured: dict = {}
    fake_usage = LLMUsage(
        provider="gemini", model_name="test", input_tokens=1, output_tokens=1, request_count=1
    )
    fake_response = _FakeLLMResponse(
        content=json.dumps({"facts": [], "theme_summary": "ok"}),
        usage=fake_usage,
        finish_reason="stop",
    )

    async def mock_generate(req):
        captured["max_tokens"] = req.max_tokens
        return fake_response

    extractor._llm.generate = mock_generate

    rd = _make_research_result()
    asyncio.run(extractor.extract_facts(theme="test", research_data=rd))

    assert captured["max_tokens"] == 16384


# ---------------------------------------------------------------------------
# Phase 4 review #2: execute_fact_extraction_only overwrite protection
# ---------------------------------------------------------------------------

def _make_minimal_research_brief(session_id: str):
    from core.models.artifacts import ResearchBrief

    return ResearchBrief(
        session_id=session_id,
        theme="テスト題材",
        research_mode="trivia",
        research_content="リサーチ本文（ダミー）",
        research_sources=[],
        queries=["q"],
        angle="ダミー",
    )


class _StubFactExtractor:
    """Drop-in replacement for FactExtractor that skips the LLM entirely."""

    def __init__(self, llm_port, config):
        self._llm = llm_port
        self.config = config
        self.last_usage = None
        self.last_fact_sheet = None

    async def extract_facts(self, theme: str, research_data, progress_log=None):
        sheet = FactSheet(
            facts=[ExtractedFact(statement="stubbed fact", surprise_score=5)],
            theme_summary="stub summary",
        )
        self.last_fact_sheet = sheet
        return sheet


def _patch_scripting_phase_for_stub(monkeypatch):
    """Swap in stubs for FactExtractor + LLMAdapterFactory so no real LLM call happens."""
    import services.script_generation.fact_extractor as fe_module
    import services.script_generation.adapters.factory as factory_module

    monkeypatch.setattr(fe_module, "FactExtractor", _StubFactExtractor, raising=True)

    class _StubFactory:
        @staticmethod
        def create(config, provider, model_override=None):
            return MagicMock()

    monkeypatch.setattr(factory_module, "LLMAdapterFactory", _StubFactory, raising=True)


def test_execute_fact_extraction_only_refuses_overwrite_without_force(
    tmp_path: Path, mock_app_config, monkeypatch
):
    """Phase 4 review #2: existing fact_sheet.json must not be silently overwritten."""
    import asyncio
    from services.pipeline.scripting_phase import execute_fact_extraction_only
    from core.session_manager import SessionManager

    _patch_scripting_phase_for_stub(monkeypatch)

    sm = SessionManager(project_root=tmp_path, session_id="overwrite_guard")
    sm.session_dir.mkdir(parents=True, exist_ok=True)

    # Pre-populate with a "human-edited" fact sheet
    edited = _make_sample_fact_sheet()
    sm.save_fact_sheet(edited)
    assert sm.has_fact_sheet()

    brief = _make_minimal_research_brief(sm.session_id)

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        asyncio.run(execute_fact_extraction_only(
            research_brief=brief,
            session_manager=sm,
            config=mock_app_config,
        ))

    # Original content must be untouched
    loaded = sm.load_fact_sheet()
    assert loaded.facts[0].entity == "OpenAI", "existing HITL content was corrupted"


def test_execute_fact_extraction_only_creates_backup_on_force(
    tmp_path: Path, mock_app_config, monkeypatch
):
    """Phase 4 review #2: force=True backs up the previous file before overwriting."""
    import asyncio
    from services.pipeline.scripting_phase import execute_fact_extraction_only
    from core.session_manager import SessionManager

    _patch_scripting_phase_for_stub(monkeypatch)

    sm = SessionManager(project_root=tmp_path, session_id="force_backup")
    sm.session_dir.mkdir(parents=True, exist_ok=True)

    edited = _make_sample_fact_sheet()
    sm.save_fact_sheet(edited)
    original_bytes = sm.get_fact_sheet_path().read_bytes()

    brief = _make_minimal_research_brief(sm.session_id)

    result = asyncio.run(execute_fact_extraction_only(
        research_brief=brief,
        session_manager=sm,
        config=mock_app_config,
        force=True,
    ))

    # New content came from the stub, not the pre-existing sheet
    assert result.theme_summary == "stub summary"
    assert sm.load_fact_sheet().theme_summary == "stub summary"

    # A timestamped backup with the original bytes must exist alongside
    backups = list(sm.session_dir.glob("fact_sheet.bak.*.json"))
    assert len(backups) == 1, f"expected exactly one backup, found {backups}"
    assert backups[0].read_bytes() == original_bytes, "backup must preserve pre-overwrite bytes"


def test_execute_fact_extraction_only_runs_normally_when_no_prior_file(
    tmp_path: Path, mock_app_config, monkeypatch
):
    """Phase 4 review #2: no backup is created when fact_sheet.json did not exist."""
    import asyncio
    from services.pipeline.scripting_phase import execute_fact_extraction_only
    from core.session_manager import SessionManager

    _patch_scripting_phase_for_stub(monkeypatch)

    sm = SessionManager(project_root=tmp_path, session_id="fresh_run")
    sm.session_dir.mkdir(parents=True, exist_ok=True)
    assert not sm.has_fact_sheet()

    brief = _make_minimal_research_brief(sm.session_id)

    result = asyncio.run(execute_fact_extraction_only(
        research_brief=brief,
        session_manager=sm,
        config=mock_app_config,
    ))

    assert sm.has_fact_sheet()
    assert result.theme_summary == "stub summary"
    # No backup files should be produced on a clean run
    assert not list(sm.session_dir.glob("fact_sheet.bak.*.json"))
