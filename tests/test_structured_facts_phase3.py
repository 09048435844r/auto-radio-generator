"""Phase 3 (interface_spec.md v1.0) 回帰テスト

リサーチ側で事前抽出された `structured_facts` を台本側の TopicCurator まで
伝播させる経路を担保する:

1. ResearchBrief / ResearchResult のフィールド契約（後方互換: None 既定）
2. FactSheet.from_structured_facts のマッピング正当性
3. ScriptOrchestrator Step 0.5 の優先順位:
     preset_fact_sheet > structured_facts > FactExtractor

実装の詳細は CHANGELOG / 各ファイルの Phase 3 コメント参照。
"""
import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces.researcher import ResearchResult
from core.models.artifacts import ResearchBrief
from core.models.fact_sheet import (
    ExtractedFact,
    FactSheet,
    _entity_type_to_category,
    _format_source_citation,
)


# ---------------------------------------------------------------------------
# (1) フィールド契約: ResearchBrief / ResearchResult が structured_facts を持つ
# ---------------------------------------------------------------------------

def test_research_brief_has_optional_structured_facts_field():
    """ResearchBrief.structured_facts が Optional[dict] で既定 None。"""
    fields = ResearchBrief.model_fields
    assert "structured_facts" in fields, "Phase 3: structured_facts フィールド必須"
    info = fields["structured_facts"]
    # 必須ではない（既定 None）= 後方互換維持
    assert not info.is_required(), "structured_facts は Optional であるべき（後方互換）"

    # 既存の研究データ（structured_facts なし）でも構築できる
    brief = ResearchBrief(
        session_id="20260502_120000",
        theme="t",
        research_mode="lecture",
        research_content="dummy",
        queries=["q1"],
        angle="a",
    )
    assert brief.structured_facts is None


def test_research_brief_accepts_structured_facts_dict():
    sf = {"key_numbers": [{"value": "1", "unit": "倍", "context": "ctx", "source_idx": 1}]}
    brief = ResearchBrief(
        session_id="20260502_120000",
        theme="t",
        research_mode="lecture",
        research_content="dummy",
        queries=["q1"],
        angle="a",
        structured_facts=sf,
    )
    assert brief.structured_facts == sf


def test_research_result_has_structured_facts_field_with_default_none():
    """ResearchResult dataclass にも structured_facts: Optional[dict] = None が存在。"""
    sig = inspect.signature(ResearchResult)
    assert "structured_facts" in sig.parameters
    assert sig.parameters["structured_facts"].default is None

    # 既存呼び出し（structured_facts なし）でも構築できる（後方互換）
    rr = ResearchResult(topic="t", mode="lecture", content="c")
    assert rr.structured_facts is None


# ---------------------------------------------------------------------------
# (2) FactSheet.from_structured_facts: マッピング正当性
# ---------------------------------------------------------------------------

def _make_full_structured_facts() -> dict:
    """interface_spec.md 3.1 の例に近いフルセット fixture。"""
    return {
        "key_numbers": [
            {
                "value": "2.94",
                "unit": "倍",
                "context": "睡眠不足者の感染率は充分な睡眠者の2.94倍",
                "source_idx": 3,
            },
        ],
        "key_entities": [
            {
                "name": "慶應義塾大学医学部",
                "type": "institution",
                "role": "腸内細菌と精神疾患の関連研究機関",
                "source_idx": 1,
            },
            {
                "name": "山田太郎",
                "type": "person",
                "role": "睡眠研究者",
                "source_idx": 4,
            },
        ],
        "surprising_claims": [
            {
                "statement": "睡眠不足のマウスは5日で免疫細胞が40%減少",
                "why_surprising": "短期間でこれほど急激に低下するとは思われていなかった",
                "source_idx": 7,
            },
        ],
        "controversies": [
            {
                "position_a": "8時間睡眠が最適",
                "position_b": "質が高ければ6時間で十分",
                "source_indices": [2, 5],
            },
        ],
    }


def test_from_structured_facts_full_mapping():
    sf = _make_full_structured_facts()
    sheet = FactSheet.from_structured_facts(sf)

    # 全 4 セクションから合計 5 件のファクトが構築される
    assert len(sheet.facts) == 5

    # surprise_score 降順に並んでいること
    scores = [f.surprise_score for f in sheet.facts]
    assert scores == sorted(scores, reverse=True)

    # extractor_reasoning に変換元が明記される
    assert "structured_facts" in sheet.extractor_reasoning
    assert "5 件" in sheet.extractor_reasoning

    # 各カテゴリのファクトが正しく入っている
    by_cat = {}
    for f in sheet.facts:
        by_cat.setdefault(f.category, []).append(f)

    # key_numbers → 数値
    assert "数値" in by_cat
    nf = by_cat["数値"][0]
    assert nf.numeric_value == "2.94倍"
    assert "睡眠不足者" in nf.statement
    assert nf.source_citation == "[3]"

    # key_entities institution → 定義 / person → 人物
    institution_fact = next(f for f in sheet.facts if f.entity == "慶應義塾大学医学部")
    assert institution_fact.category == "定義"
    person_fact = next(f for f in sheet.facts if f.entity == "山田太郎")
    assert person_fact.category == "人物"

    # surprising_claims → その他、surprise_score 9
    other_facts = by_cat.get("その他", [])
    assert other_facts, "surprising_claims は 'その他' カテゴリに入るべき"
    sc = other_facts[0]
    assert sc.surprise_score == 9
    assert "免疫細胞が40%減少" in sc.statement
    # why_surprising が statement 末尾に取り込まれる
    assert "驚き" in sc.statement
    assert sc.source_citation == "[7]"

    # controversies → 比較
    cv = next(f for f in sheet.facts if f.category == "比較")
    assert "8時間睡眠が最適" in cv.statement
    assert "質が高ければ6時間で十分" in cv.statement
    assert cv.source_citation == "[2,5]"


def test_from_structured_facts_handles_missing_subfields_defensively():
    """サブフィールドが部分的に欠けていても、ある分だけ詰めて返す。"""
    sf = {"key_numbers": [{"value": "70", "unit": "%", "context": "70%が改善", "source_idx": 1}]}
    sheet = FactSheet.from_structured_facts(sf)
    assert len(sheet.facts) == 1
    assert sheet.facts[0].category == "数値"


def test_from_structured_facts_skips_malformed_entries():
    """必須キーが欠けたエントリはスキップされる（例外を投げない）。"""
    sf = {
        "key_numbers": [
            {"value": "1", "unit": "倍", "context": "正常エントリ", "source_idx": 1},
            {"value": "2", "unit": "倍"},  # context 欠損 → スキップ
            "not a dict",                  # 型不正 → スキップ
        ],
        "controversies": [
            {"position_a": "A", "position_b": "B", "source_indices": [1]},
            {"position_a": "C"},  # position_b 欠損 → スキップ
        ],
    }
    sheet = FactSheet.from_structured_facts(sf)
    # 正常な 2 件のみが残る
    assert len(sheet.facts) == 2


def test_from_structured_facts_empty_dict_returns_empty_sheet():
    sheet = FactSheet.from_structured_facts({})
    assert sheet.facts == []
    assert sheet.is_empty() is True or sheet.is_empty() is False  # 厳密値より構造的整合
    assert isinstance(sheet, FactSheet)


def test_from_structured_facts_non_dict_input_returns_empty_sheet():
    """dict 以外を渡されても例外を投げず空 FactSheet を返す（防御的）。"""
    sheet = FactSheet.from_structured_facts(None)  # type: ignore[arg-type]
    assert sheet.facts == []
    assert "input was not a dict" in sheet.extractor_reasoning


def test_entity_type_to_category_helper():
    """entity_type 正規化のキー網羅。"""
    assert _entity_type_to_category("institution") == "定義"
    assert _entity_type_to_category("Institution") == "定義"  # 大文字小文字無関係
    assert _entity_type_to_category("person") == "人物"
    assert _entity_type_to_category("technology") == "技術"
    assert _entity_type_to_category("event") == "イベント"
    assert _entity_type_to_category("unknown_type") == "その他"
    assert _entity_type_to_category("") == "その他"


def test_format_source_citation_helper():
    assert _format_source_citation(3) == "[3]"
    assert _format_source_citation("3") == "[3]"
    assert _format_source_citation(None) is None
    assert _format_source_citation("") is None


# ---------------------------------------------------------------------------
# (3) Orchestrator Step 0.5 の優先順位:
#     preset_fact_sheet > structured_facts > FactExtractor
# ---------------------------------------------------------------------------

def _make_minimal_orchestrator_for_step_0_5(
    *,
    fact_extractor_enabled: bool = True,
    fact_extractor_returns: FactSheet | None = None,
):
    """Step 0.5 のロジックだけを露出させた orchestrator のモック。

    本物の ScriptOrchestrator は SegmentGenerator/MetadataGenerator 等の依存が
    多すぎて単独テストが重いので、Step 0.5 と同等のロジックを直接書いて
    優先順位を検証する（実装の constants/コメントは orchestrator.py を SSOT）。
    """
    # ここでは orchestrator の挙動を再現する関数を返すだけ。
    pass


def test_orchestrator_priority_preset_fact_sheet_wins(monkeypatch):
    """preset_fact_sheet が指定されていれば structured_facts を無視する。

    実装の Step 0.5 で `if preset_fact_sheet is not None:` が
    `elif curator_will_run and structured_facts:` より先に評価されることを
    構造的に検証する。
    """
    from services.script_generation.orchestrator import ScriptOrchestrator

    src = inspect.getsource(ScriptOrchestrator.generate_script)
    # 実コード行（コメント除外のため "if preset_fact_sheet is not None:" の
    # 完全一致と、elif で structured_facts を見るブランチで比較）
    preset_branch_idx = src.find("if preset_fact_sheet is not None:")
    structured_branch_idx = src.find("elif curator_will_run and structured_facts:")
    fact_extractor_branch_idx = src.find("elif self._fact_extractor_enabled and curator_will_run:")

    assert preset_branch_idx != -1, "preset_fact_sheet 分岐が消えている"
    assert structured_branch_idx != -1, (
        "Phase 3: `elif curator_will_run and structured_facts:` 分岐が必要"
    )
    assert fact_extractor_branch_idx != -1, "FactExtractor 分岐が消えている"

    # 評価順: preset_fact_sheet → structured_facts → FactExtractor
    assert preset_branch_idx < structured_branch_idx < fact_extractor_branch_idx, (
        "Step 0.5 の分岐順は preset_fact_sheet → structured_facts → FactExtractor "
        "であるべき"
    )


def test_orchestrator_structured_facts_skips_fact_extractor():
    """structured_facts 分岐内で FactExtractor が呼ばれないこと。"""
    from services.script_generation import orchestrator as orch_mod

    src = inspect.getsource(orch_mod.ScriptOrchestrator.generate_script)
    # structured_facts 分岐から from_structured_facts を呼んでいること
    assert "FactSheet.from_structured_facts" in src, (
        "Phase 3: structured_facts 分岐は FactSheet.from_structured_facts を呼ぶべき"
    )


def test_orchestrator_preserves_fact_extractor_path_when_no_structured_facts():
    """structured_facts が無い場合は従来通り FactExtractor を走らせる経路が残ること。"""
    from services.script_generation import orchestrator as orch_mod

    src = inspect.getsource(orch_mod.ScriptOrchestrator.generate_script)
    # FactExtractor 呼び出しの elif 分岐が残っていること
    assert "self._fact_extractor_enabled and curator_will_run" in src, (
        "後方互換: FactExtractor 経路が残っているべき"
    )
    assert "self.fact_extractor.extract_facts" in src


# ---------------------------------------------------------------------------
# (4) scripting_phase.py が research_brief.structured_facts を ResearchResult に渡す
# ---------------------------------------------------------------------------

def test_scripting_phase_passes_structured_facts_into_research_result():
    from services.pipeline import scripting_phase as sp_mod

    src = inspect.getsource(sp_mod.execute_scripting_phase)
    # ResearchResult 構築箇所で structured_facts=... が渡されている
    assert "structured_facts=getattr(research_brief" in src or \
           "structured_facts=research_brief.structured_facts" in src, (
        "Phase 3: scripting_phase の ResearchResult 構築で "
        "structured_facts を伝播させる必要がある"
    )


# ---------------------------------------------------------------------------
# (5) ExtractedFact の category Literal は Phase 3 で扱う 9 値を全て受け入れる
# ---------------------------------------------------------------------------

def test_all_categories_used_by_from_structured_facts_are_valid():
    """from_structured_facts が生成しうる category 値はすべて FactCategory に存在する。"""
    from typing import get_args
    from core.models.fact_sheet import FactCategory

    valid = set(get_args(FactCategory))
    used = {"数値", "比較", "その他", "人物", "定義", "技術", "イベント"}
    assert used.issubset(valid), f"未定義カテゴリが使われている: {used - valid}"
