"""PR-G: FactExtractor の自己矛盾検出テスト。

本運用 (output/20260424_220840) で qwen3:8b が
  - extractor_reasoning に「数値系ファクト 5 件を抽出」と書きながら
  - facts 配列を空のまま返す
症状が観測された。PR-E のプロンプト改善でも残存している小型モデルの
構造化出力能力限界。

PR-G は (A) パーサ層で自己矛盾を検出して RuntimeError を送出 + (B)
prompts.yaml に整合性制約を明文化、の二段で対処する。本ファイルは (A) の
検出ロジックの正確性を担保し、加えて (B) のプロンプト文言が将来の
リファクタで消えないことを回帰的に保証する。
"""
import json
import logging
from unittest.mock import MagicMock

import pytest

from core.models.fact_sheet import ExtractedFact, FactSheet


# ---------------------------------------------------------------------------
# Helpers (test_fact_extractor.py と同じパターン)
# ---------------------------------------------------------------------------

def _make_fact_extractor_for_parse(mock_app_config):
    from services.script_generation.fact_extractor import FactExtractor

    mock_port = MagicMock()
    mock_port.provider_name = "gemini"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "gemini-2.5-flash"
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_facts = 30
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_tokens = 8192

    return FactExtractor(mock_port, mock_app_config)


# ---------------------------------------------------------------------------
# 案 A: 自己矛盾の検出（陽性ケース）
# ---------------------------------------------------------------------------

def test_self_inconsistency_detected_when_reasoning_claims_count_but_facts_empty(mock_app_config, caplog):
    """本運用で観測された症状そのまま: reasoning に「5 件」と書かれて facts=[]。"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [],
        "theme_summary": "Qwen3.6-26Bは...",
        "extractor_reasoning": "数値系ファクト5件を抽出。意外性スコア7〜8の「一般人にとって新情報」を優先。",
    })

    with caplog.at_level(logging.ERROR, logger="services.script_generation.fact_extractor"):
        with pytest.raises(RuntimeError, match="self-inconsistency"):
            extractor._parse_fact_sheet_response(raw)

    # PR-C/F の logger.error 経路に乗ること
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("self-inconsistency" in r.getMessage() for r in error_records), \
        "PR-G は自己矛盾検出時に logger.error を呼ぶべき"
    # メッセージに reasoning 文言が含まれていること（debug 時の手がかり）
    assert any("5件" in r.getMessage() or "5 件" in r.getMessage() for r in error_records), \
        "logger.error メッセージに reasoning の内容が含まれるべき"


@pytest.mark.parametrize("reasoning_text,description", [
    ("数値系ファクト5件を抽出。", "全角・半角混在 N件"),
    ("ファクト 5 件を抽出した", "半角スペース付き"),
    ("3個のファクトを選定", "個 単位"),
    ("最低5つを目標としたが情報が薄かった", "つ 単位"),
    ("10件抽出した", "2 桁"),
    ("数値ファクト3件 + 比較1件で合計4件", "複数の件数言及"),
])
def test_self_inconsistency_detected_for_various_count_phrasings(mock_app_config, reasoning_text, description):
    """件数言及の様々な表現パターンで検出されることを担保。"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [],
        "theme_summary": "summary",
        "extractor_reasoning": reasoning_text,
    })

    with pytest.raises(RuntimeError, match="self-inconsistency"):
        extractor._parse_fact_sheet_response(raw)


# ---------------------------------------------------------------------------
# 案 A: 偽陽性回避（陰性ケース）
# ---------------------------------------------------------------------------

def test_no_self_inconsistency_when_facts_present_even_with_count_in_reasoning(mock_app_config):
    """facts に 1 件以上ある場合は、reasoning に件数言及があってもエラーにしない。"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [
            {"statement": "テスト事実", "category": "数値", "surprise_score": 5},
        ],
        "theme_summary": "summary",
        "extractor_reasoning": "数値系ファクト1件を抽出した",
    })

    # 正常終了するべき
    sheet = extractor._parse_fact_sheet_response(raw)
    assert len(sheet.facts) == 1


def test_no_self_inconsistency_when_reasoning_empty(mock_app_config):
    """extractor_reasoning が空文字なら、件数検査自体スキップ。"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [],
        "theme_summary": "summary",
        "extractor_reasoning": "",
    })

    # facts=[] でも reasoning が空なら RuntimeError は出ない（この症状は別案件）
    sheet = extractor._parse_fact_sheet_response(raw)
    assert sheet.facts == []
    assert sheet.extractor_reasoning == ""


def test_no_self_inconsistency_when_reasoning_lacks_count(mock_app_config):
    """reasoning が件数言及を含まない（"判断材料なし" 等）場合は検出しない。"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [],
        "theme_summary": "summary",
        "extractor_reasoning": "リサーチデータに判断材料となる具体的事実が見当たらず、抽出を控えた。",
    })

    # 件数言及がないので self-inconsistency と見做さない
    sheet = extractor._parse_fact_sheet_response(raw)
    assert sheet.facts == []


def test_no_false_positive_for_percentage_in_reasoning(mock_app_config):
    """数値だけ含む reasoning（例: "70% の精度"）は件数言及ではないので誤検知しない。"""
    extractor = _make_fact_extractor_for_parse(mock_app_config)
    raw = json.dumps({
        "facts": [],
        "theme_summary": "summary",
        "extractor_reasoning": "リサーチには 70% という数字があったが、文脈不足で抽出を見送った",
    })

    # "70%" は件数言及ではないので RuntimeError なし
    sheet = extractor._parse_fact_sheet_response(raw)
    assert sheet.facts == []


# ---------------------------------------------------------------------------
# 案 B: prompts.yaml への整合性制約追加の回帰テスト
# ---------------------------------------------------------------------------

def test_fact_extractor_prompt_declares_self_consistency_constraint():
    """prompts.yaml の禁止事項に「reasoning と facts の整合性」が明示されている。"""
    from core.prompt_manager import PromptManager
    p = PromptManager().get_prompt("orchestrator", "fact_extractor")

    # 自己矛盾を禁止する文言
    assert "件" in p and "facts 配列" in p
    assert "自己矛盾" in p or "整合性" in p
    # PR-G がパーサ層でも検知することを LLM に通知する文言（"必ず一致"）
    assert "必ず一致" in p or "整合性は必須" in p


# ---------------------------------------------------------------------------
# 統合: 上位 extract_facts() からの自己矛盾検出
# ---------------------------------------------------------------------------

def test_extract_facts_propagates_self_inconsistency_runtime_error(mock_app_config, caplog):
    """extract_facts() レベルでも自己矛盾は RuntimeError として伝播する
    （orchestrator の except Exception でフォールスルーされる契約を担保）。
    """
    import asyncio
    from core.models.usage import LLMUsage

    extractor = _make_fact_extractor_for_parse(mock_app_config)

    # finish_reason="stop"（正常終了扱い）で、自己矛盾な内容を返す mock
    fake_usage = LLMUsage(
        provider="gemini", model_name="test",
        input_tokens=10, output_tokens=10, request_count=1,
    )

    class _FakeResponse:
        def __init__(self, content, usage, finish_reason):
            self.content = content
            self.usage = usage
            self.finish_reason = finish_reason

    # 2026-05-06: 2 段階アーキテクチャでも自己矛盾は検出されることを担保。
    # Phase 1 が markdown を返したが「抽出方針」に「N件抽出」と書きながら
    # `### Fact N` ブロックを 0 件しか出さない症状（旧 JSON 経路の自己矛盾と同型）
    raw = (
        "# FactSheet\n\n"
        "## テーマ要約\nsummary\n\n"
        "## 抽出方針\n数値系ファクト5件を抽出した\n\n"
        "## ファクト一覧\n"
        # 意図的に Fact ブロックを 0 件のままにする（自己矛盾を再現）
    )

    async def mock_generate(req):
        return _FakeResponse(raw, fake_usage, "stop")

    extractor._llm.generate = mock_generate

    rd = MagicMock(mode="trivia", content="dummy research content")

    with caplog.at_level(logging.ERROR, logger="services.script_generation.fact_extractor"):
        with pytest.raises(RuntimeError, match="self-inconsistency"):
            asyncio.run(extractor.extract_facts(theme="t", research_data=rd))

    # PR-C/F の logger.error がきちんと呼ばれていること
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("self-inconsistency" in r.getMessage() for r in error_records)
