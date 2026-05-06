"""FactExtractor 2 段階アーキテクチャテスト

2026-05-06: SegmentGenerator と同型の Phase 1 (markdown 生成) +
Phase 2 (正規表現で FactSheet 復元) パターンへ移行した FactExtractor の検証。

担保する内容:
1. Phase 1 (_generate_creative_markdown) は markdown 生成プロンプトを使い、
   response_format="text" で呼び出し、length 切り詰めは fail-fast
2. Phase 2 (_parse_markdown_to_fact_sheet) は markdown を Pydantic FactSheet に
   復元する。各分岐:
   - 正常な markdown → FactSheet
   - 未知カテゴリ → "その他" にフォールバック
   - 範囲外 surprise_score → 1-10 にクランプ
   - 「なし」「N/A」「-」等 → None
   - 空 markdown → ValueError
   - 0 件 + reasoning に件数 → 自己矛盾 RuntimeError
   - 0 件 + reasoning に件数なし → ValueError
   - 必須フィールド「記述」欠落 → そのファクトはスキップ
3. _save_markdown_fact_sheet が fact_sheet_phase1.md を作る
4. 統合: extract_facts が 2 段階フローで FactSheet を返す
"""
import asyncio
import json
import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces.llm_port import LLMRequest, LLMResponse
from core.models import LLMUsage
from core.models.fact_sheet import FactSheet
from services.script_generation.fact_extractor import FactExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extractor(mock_app_config, markdown_output_dir=None) -> FactExtractor:
    mock_port = MagicMock()
    mock_port.provider_name = "ollama"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "qwen3.5-122b-a10b"
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_facts = 30
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_tokens = 12288

    return FactExtractor(mock_port, mock_app_config, markdown_output_dir=markdown_output_dir)


def _research_result(content: str = "リサーチ本文ダミー" * 50, mode: str = "trivia"):
    rd = MagicMock()
    rd.content = content
    rd.mode = mode
    return rd


def _valid_markdown_two_facts() -> str:
    return (
        "# FactSheet\n\n"
        "## テーマ要約\n"
        "Hugging Face の評価額やマルウェア事件など 2024 年の AI プラットフォーム動向。\n\n"
        "## 抽出方針\n"
        "数値系 1 件と比較系 1 件を意外性スコア降順で抽出した。\n\n"
        "## ファクト一覧\n\n"
        "### Fact 1\n"
        "- **カテゴリ**: 数値\n"
        "- **意外性スコア**: 9\n"
        "- **数値**: 45億ドル\n"
        "- **主語**: Hugging Face\n"
        "- **出典**: 検索結果1\n"
        "- **記述**: Hugging Face は 2024 年に評価額 45 億ドルへ到達した。\n\n"
        "### Fact 2\n"
        "- **カテゴリ**: 比較\n"
        "- **意外性スコア**: 7\n"
        "- **数値**: 90万超\n"
        "- **主語**: Hugging Face Hub\n"
        "- **出典**: なし\n"
        "- **記述**: Hub にホストされる AI モデル数は 90 万を超える。\n"
    )


# ---------------------------------------------------------------------------
# (1) Phase 1: _generate_creative_markdown
# ---------------------------------------------------------------------------

def test_phase1_uses_text_response_format(mock_app_config):
    extractor = _make_extractor(mock_app_config)
    captured = {}

    async def mock_gen(req: LLMRequest) -> LLMResponse:
        captured["request"] = req
        return LLMResponse(
            content=_valid_markdown_two_facts(),
            usage=LLMUsage(provider="ollama", model_name="x", input_tokens=10, output_tokens=20),
            finish_reason="stop",
        )

    extractor._llm.generate = mock_gen
    asyncio.run(extractor._generate_creative_markdown(theme="t", research_data=_research_result()))

    req = captured["request"]
    assert req.response_format == "text", "Phase 1 は JSON モードを使わない（markdown 自由記述）"
    assert req.max_tokens == 12288
    # temperature は既存値 0.2 を維持
    assert req.temperature == 0.2


def test_phase1_uses_creative_prompt(mock_app_config):
    extractor = _make_extractor(mock_app_config)
    captured = {}

    async def mock_gen(req: LLMRequest) -> LLMResponse:
        captured["system_prompt"] = req.system_prompt
        return LLMResponse(
            content=_valid_markdown_two_facts(),
            usage=LLMUsage(provider="ollama", model_name="x", input_tokens=10, output_tokens=20),
            finish_reason="stop",
        )

    extractor._llm.generate = mock_gen
    asyncio.run(extractor._generate_creative_markdown(theme="t", research_data=_research_result()))

    sp = captured["system_prompt"]
    # markdown 生成プロンプトに含まれる固有文字列で識別
    assert "Markdown" in sp
    assert "### Fact" in sp, "fact_extractor_creative プロンプトには Fact ブロック例があるはず"


def test_phase1_fail_fast_on_length_truncation(mock_app_config):
    extractor = _make_extractor(mock_app_config)

    async def mock_gen(_req):
        return LLMResponse(
            content="### Fact 1\n- **カテゴリ**: 数値",  # 中途半端な markdown
            usage=LLMUsage(provider="ollama", model_name="x", input_tokens=10, output_tokens=12288),
            finish_reason="length",
        )

    extractor._llm.generate = mock_gen
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(extractor._generate_creative_markdown(theme="t", research_data=_research_result()))


# ---------------------------------------------------------------------------
# (2) Phase 2: _parse_markdown_to_fact_sheet — 正常系
# ---------------------------------------------------------------------------

def test_phase2_parses_two_facts_correctly(mock_app_config):
    extractor = _make_extractor(mock_app_config)
    fs = extractor._parse_markdown_to_fact_sheet(_valid_markdown_two_facts())

    assert isinstance(fs, FactSheet)
    assert len(fs.facts) == 2
    # surprise_score 降順で並ぶ
    assert fs.facts[0].surprise_score == 9
    assert fs.facts[1].surprise_score == 7
    # フィールド復元
    f1 = fs.facts[0]
    assert f1.category == "数値"
    assert f1.numeric_value == "45億ドル"
    assert f1.entity == "Hugging Face"
    assert f1.source_citation == "検索結果1"
    assert "45 億ドル" in f1.statement

    # 「なし」は None に正規化
    f2 = fs.facts[1]
    assert f2.source_citation is None

    # サマリ・方針も復元
    assert "Hugging Face" in fs.theme_summary
    assert "数値系" in fs.extractor_reasoning


def test_phase2_extract_md_section_returns_empty_when_missing(mock_app_config):
    extractor = _make_extractor(mock_app_config)
    md = "## テーマ要約\nfoo\n\n### Fact 1\n- **記述**: x\n- **カテゴリ**: 数値\n- **意外性スコア**: 5\n"
    # 「抽出方針」セクションがない → 空文字列で返る
    fs = extractor._parse_markdown_to_fact_sheet(md)
    assert fs.theme_summary == "foo"
    assert fs.extractor_reasoning == ""


# ---------------------------------------------------------------------------
# (3) Phase 2: 防御的フォールバック分岐
# ---------------------------------------------------------------------------

def test_phase2_unknown_category_falls_back_to_その他(mock_app_config, caplog):
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "## 抽出方針\ny\n\n"
        "### Fact 1\n"
        "- **カテゴリ**: 全く知らないカテゴリ\n"
        "- **意外性スコア**: 5\n"
        "- **記述**: 未知カテゴリのテストファクト\n"
    )
    with caplog.at_level(logging.WARNING, logger="services.script_generation.fact_extractor"):
        fs = extractor._parse_markdown_to_fact_sheet(md)

    assert len(fs.facts) == 1
    assert fs.facts[0].category == "その他"
    assert any("Unknown category" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("score_text, expected", [
    ("0", 1),     # 下限クランプ
    ("11", 10),   # 上限クランプ
    ("-5", 5),    # 負号付きは数字のみ抽出 → 5
    ("7点", 7),    # 数字以外混在
    ("8 / 10", 8),
    ("abc", 5),   # パース不能 → デフォルト 5
])
def test_phase2_clamps_surprise_score(mock_app_config, score_text, expected):
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "### Fact 1\n"
        f"- **カテゴリ**: 数値\n"
        f"- **意外性スコア**: {score_text}\n"
        f"- **記述**: スコアテストファクト\n"
    )
    fs = extractor._parse_markdown_to_fact_sheet(md)
    assert len(fs.facts) == 1
    assert fs.facts[0].surprise_score == expected


@pytest.mark.parametrize("raw_value", ["なし", "無し", "N/A", "n/a", "null", "-", "ー", "（なし）", "(なし)"])
def test_phase2_normalizes_none_strings(mock_app_config, raw_value):
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "### Fact 1\n"
        f"- **カテゴリ**: 数値\n"
        f"- **意外性スコア**: 5\n"
        f"- **数値**: {raw_value}\n"
        f"- **主語**: {raw_value}\n"
        f"- **出典**: {raw_value}\n"
        f"- **記述**: optional フィールドが None 化されることのテスト\n"
    )
    fs = extractor._parse_markdown_to_fact_sheet(md)
    f = fs.facts[0]
    assert f.numeric_value is None
    assert f.entity is None
    assert f.source_citation is None


def test_phase2_keeps_real_values_in_optional_fields(mock_app_config):
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "### Fact 1\n"
        "- **カテゴリ**: 数値\n"
        "- **意外性スコア**: 5\n"
        "- **数値**: 45億ドル\n"
        "- **主語**: Apple\n"
        "- **出典**: 検索結果3\n"
        "- **記述**: 実値を持つ optional フィールド\n"
    )
    fs = extractor._parse_markdown_to_fact_sheet(md)
    f = fs.facts[0]
    assert f.numeric_value == "45億ドル"
    assert f.entity == "Apple"
    assert f.source_citation == "検索結果3"


def test_phase2_skips_fact_with_missing_statement(mock_app_config, caplog):
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "### Fact 1\n"
        "- **カテゴリ**: 数値\n"
        "- **意外性スコア**: 5\n"
        "- **記述**: 有効なファクト\n\n"
        "### Fact 2\n"
        "- **カテゴリ**: 数値\n"
        "- **意外性スコア**: 5\n"
        "（記述が無い壊れた Fact）\n"
    )
    fs = extractor._parse_markdown_to_fact_sheet(md)
    # Fact 1 のみ残る
    assert len(fs.facts) == 1
    assert "有効" in fs.facts[0].statement


def test_phase2_raises_value_error_for_empty_markdown(mock_app_config):
    extractor = _make_extractor(mock_app_config)
    with pytest.raises(ValueError, match="empty"):
        extractor._parse_markdown_to_fact_sheet("")
    with pytest.raises(ValueError, match="empty"):
        extractor._parse_markdown_to_fact_sheet("   \n\n")


def test_phase2_raises_value_error_when_no_fact_blocks(mock_app_config):
    """Fact ブロックが全く無く reasoning にも件数言及が無ければ ValueError"""
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "## 抽出方針\n判断材料となるファクトが見当たらず、抽出を見送った\n"
    )
    with pytest.raises(ValueError, match="No valid Fact blocks"):
        extractor._parse_markdown_to_fact_sheet(md)


def test_phase2_raises_runtime_error_on_self_inconsistency(mock_app_config):
    """0 件出力なのに「N件抽出」と reasoning に書く自己矛盾を検出する"""
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "## 抽出方針\n数値系 5 件を抽出した\n"
        # ファクト 0 件
    )
    with pytest.raises(RuntimeError, match="self-inconsistency"):
        extractor._parse_markdown_to_fact_sheet(md)


def test_phase2_handles_alternate_label_format(mock_app_config):
    """'**カテゴリ:**' 末尾コロン形式（`**foo:** value`）も寛容に拾う"""
    extractor = _make_extractor(mock_app_config)
    md = (
        "## テーマ要約\nx\n\n"
        "### Fact 1\n"
        "- **カテゴリ:** 数値\n"
        "- **意外性スコア:** 5\n"
        "- **記述:** ラベル末尾コロン形式\n"
    )
    fs = extractor._parse_markdown_to_fact_sheet(md)
    assert len(fs.facts) == 1
    assert fs.facts[0].category == "数値"


# ---------------------------------------------------------------------------
# (4) _save_markdown_fact_sheet
# ---------------------------------------------------------------------------

def test_save_markdown_fact_sheet_writes_file(tmp_path: Path, mock_app_config):
    extractor = _make_extractor(mock_app_config, markdown_output_dir=tmp_path)
    md = "# FactSheet\n\n## テーマ要約\ntest\n"
    extractor._save_markdown_fact_sheet(md)

    output = tmp_path / "fact_sheet_phase1.md"
    assert output.exists()
    assert output.read_text(encoding="utf-8") == md


def test_save_markdown_fact_sheet_no_op_when_no_dir(mock_app_config):
    """markdown_output_dir=None なら例外なく no-op"""
    extractor = _make_extractor(mock_app_config, markdown_output_dir=None)
    extractor._save_markdown_fact_sheet("# anything")  # raises nothing


def test_save_markdown_fact_sheet_failopens_on_io_error(tmp_path: Path, mock_app_config, caplog):
    """書き込み不能でも例外を伝播せず WARNING のみ"""
    # ファイル書き込みを失敗させるため、ディレクトリ位置にファイルを置く
    blocked = tmp_path / "blocked.md"
    blocked.write_text("x")
    extractor = _make_extractor(mock_app_config, markdown_output_dir=blocked)
    with caplog.at_level(logging.WARNING, logger="services.script_generation.fact_extractor"):
        extractor._save_markdown_fact_sheet("# foo")  # raises nothing

    assert any("Failed to save fact_sheet_phase1.md" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# (5) Integration: extract_facts uses 2-phase flow + saves markdown
# ---------------------------------------------------------------------------

def test_extract_facts_returns_fact_sheet_via_two_phase_flow(tmp_path: Path, mock_app_config):
    extractor = _make_extractor(mock_app_config, markdown_output_dir=tmp_path)

    async def mock_gen(_req):
        return LLMResponse(
            content=_valid_markdown_two_facts(),
            usage=LLMUsage(provider="ollama", model_name="x", input_tokens=100, output_tokens=200),
            finish_reason="stop",
        )

    extractor._llm.generate = mock_gen
    fs = asyncio.run(extractor.extract_facts(theme="t", research_data=_research_result()))

    assert isinstance(fs, FactSheet)
    assert len(fs.facts) == 2
    # markdown が保存されている
    assert (tmp_path / "fact_sheet_phase1.md").exists()
    # last_fact_sheet / last_usage がセットされている
    assert extractor.last_fact_sheet is fs
    assert extractor.last_usage.input_tokens == 100


def test_extract_facts_propagates_phase1_length_truncation(mock_app_config):
    extractor = _make_extractor(mock_app_config)

    async def mock_gen(_req):
        return LLMResponse(
            content="partial markdown",
            usage=LLMUsage(provider="ollama", model_name="x", input_tokens=10, output_tokens=12288),
            finish_reason="length",
        )

    extractor._llm.generate = mock_gen
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        asyncio.run(extractor.extract_facts(theme="t", research_data=_research_result()))


def test_extract_facts_phase2_value_error_propagates(mock_app_config):
    """Phase 2 が ValueError を出した場合、extract_facts はそれを伝播する
    （上位 orchestrator がフェイルオープン処理する契約）
    """
    extractor = _make_extractor(mock_app_config)

    async def mock_gen(_req):
        return LLMResponse(
            content="# 全く markdown 形式に従わない出力",
            usage=LLMUsage(provider="ollama", model_name="x", input_tokens=10, output_tokens=20),
            finish_reason="stop",
        )

    extractor._llm.generate = mock_gen
    with pytest.raises(ValueError, match="No valid Fact blocks"):
        asyncio.run(extractor.extract_facts(theme="t", research_data=_research_result()))


# ---------------------------------------------------------------------------
# (6) Constructor: markdown_output_dir kwarg
# ---------------------------------------------------------------------------

def test_constructor_accepts_markdown_output_dir(tmp_path: Path, mock_app_config):
    extractor = _make_extractor(mock_app_config, markdown_output_dir=tmp_path)
    assert extractor.markdown_output_dir == tmp_path


def test_constructor_defaults_markdown_output_dir_to_none(mock_app_config):
    extractor = _make_extractor(mock_app_config)
    assert extractor.markdown_output_dir is None


def test_constructor_max_tokens_defaults_to_12288(mock_app_config):
    """max_tokens の既定値が 12288（2 段階移行に伴う引き上げ後の値）"""
    # config で max_tokens を未設定にして constructor 側 default が効くケースを再現
    mock_port = MagicMock()
    mock_port.provider_name = "ollama"

    mock_app_config.yaml.script_generator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.curator_model = "qwen3.5-122b-a10b"
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor = MagicMock()
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.model = ""
    mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_facts = 30
    # max_tokens 属性を未設定（getattr の default が効く）
    del mock_app_config.yaml.script_generator.orchestrator.fact_extractor.max_tokens

    ex = FactExtractor(mock_port, mock_app_config)
    assert ex.max_tokens == 12288
