"""research_import 経路で structured_facts が ResearchResult に伝播することの回帰テスト

2026-05-06: workflow.py:1850 の `preloaded_research = ResearchResult(...)` 構築時に
`structured_facts=brief.structured_facts` が漏れており、Gradio UI から
research_import_filepath 経由で台本生成すると Phase 3 連携が一切働かなかった
（FactSheet.from_structured_facts 分岐が常にスキップされ FactExtractor へ
フォールバックする）バグへの回帰テスト。

担保する内容:
1. workflow.py の preloaded_research 構築箇所に
   `structured_facts=brief.structured_facts` の代入が存在する（構造的契約）
2. run_workflow_sync 経由で structured_facts 入りの brief をインポートすると、
   _execute_gradio_scripting_phase に渡る preloaded_research_data の
   structured_facts が brief のものと一致する（動作レベル）
"""
import json
import re
from pathlib import Path

import pytest

from core.interfaces import ResearchResult
from core.models.artifacts import ResearchBrief
import workflow as wf


WORKFLOW_SRC_PATH = Path(__file__).resolve().parent.parent / "workflow.py"


# ---------------------------------------------------------------------------
# (1) 構造的契約: ResearchResult 構築箇所に structured_facts が含まれている
# ---------------------------------------------------------------------------

def test_preloaded_research_carries_structured_facts():
    """workflow.py の preloaded_research 構築ブロックに
    `structured_facts=brief.structured_facts` が含まれている。"""
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")

    # `preloaded_research = ResearchResult(...)` ブロックを抽出
    block = re.search(
        r"preloaded_research\s*=\s*ResearchResult\((?P<args>(?:.|\n)+?)\)",
        src,
    )
    assert block is not None, (
        "workflow.py に `preloaded_research = ResearchResult(...)` ブロックが見つからない（構造変更？）"
    )
    args = block.group("args")
    assert "structured_facts=brief.structured_facts" in args, (
        "research_import 経路の ResearchResult 構築で structured_facts が抜けている。"
        "リサーチ側で抽出されたファクトが台本側 Phase 3 に届かず、FactSheet.from_structured_facts "
        "分岐がスキップされて FactExtractor へフォールバックするバグが復活する。"
    )


# ---------------------------------------------------------------------------
# (2) 動作レベル: structured_facts が下流フェーズに伝播する
# ---------------------------------------------------------------------------

class _StopWorkflow(Exception):
    """テスト用センチネル: スクリプト生成段階に到達したら捕捉する"""


def _write_brief_with_structured_facts(path: Path) -> tuple[Path, dict]:
    structured_facts = {
        "key_numbers": [
            {"value": "0.42", "unit": "(SMD)", "context": "HIIT vs MICT 効果サイズ", "source_idx": 1},
            {"value": "95", "unit": "%", "context": "信頼区間 0.27-0.57", "source_idx": 1},
        ],
        "key_entities": [
            {"name": "HIIT", "type": "concept", "role": "高強度インターバルトレーニング", "source_idx": 1},
        ],
        "surprising_claims": [
            {"statement": "HIIT は MICT の37%の時間で同等以上の効果", "why_surprising": "時間効率の常識を覆す", "source_idx": 1},
        ],
        "controversies": [],
    }
    brief = ResearchBrief(
        session_id="20260506_test",
        theme="HIIT メタアナリシス",
        research_mode="lecture",
        research_content="本物のリサーチ本文を模した文字列。" * 30,
        research_sources=[],
        queries=["クエリ1"],
        angle="数値根拠で語る",
        structured_facts=structured_facts,
    )
    brief_path = path / "research_brief.json"
    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")
    return brief_path, structured_facts


def test_imported_brief_structured_facts_propagates_to_scripting_phase(tmp_path, monkeypatch):
    """structured_facts 入りの brief をインポートすると、preloaded_research_data に
    structured_facts が乗って _execute_gradio_scripting_phase まで届く。"""
    brief_path, expected_facts = _write_brief_with_structured_facts(tmp_path)

    captured: dict = {}

    async def _capture_and_stop(*args, **kwargs):
        captured["preloaded_research_data"] = kwargs.get("preloaded_research_data")
        raise _StopWorkflow("captured; aborting downstream phases")

    async def _ok_prereq(*args, **kwargs):
        return True, None

    monkeypatch.setattr(wf, "_execute_gradio_scripting_phase", _capture_and_stop)
    monkeypatch.setattr(wf, "check_prerequisites", _ok_prereq)
    monkeypatch.setattr(wf, "PROJECT_ROOT", tmp_path)

    wf.run_workflow_sync(
        theme="Imported Research",  # app.py の placeholder
        research_import_filepath=str(brief_path),
    )

    pr = captured.get("preloaded_research_data")
    assert pr is not None, "preloaded_research_data が _execute_gradio_scripting_phase に届いていない"
    assert isinstance(pr, ResearchResult), f"型が想定外: {type(pr)}"
    assert pr.structured_facts == expected_facts, (
        f"structured_facts が伝播していない / 値が変質している。\n"
        f"期待: {expected_facts}\n"
        f"実際: {pr.structured_facts}"
    )


def test_imported_brief_without_structured_facts_remains_none(tmp_path, monkeypatch):
    """structured_facts が無い旧形式 brief をインポートしても、None で正しく届く（後方互換）。"""
    brief = ResearchBrief(
        session_id="20260506_legacy",
        theme="legacy theme",
        research_mode="lecture",
        research_content="本文。" * 50,
        research_sources=[],
        queries=["q"],
        angle="a",
        # structured_facts は未指定 → 既定 None
    )
    brief_path = tmp_path / "research_brief.json"
    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")

    captured: dict = {}

    async def _capture_and_stop(*args, **kwargs):
        captured["preloaded_research_data"] = kwargs.get("preloaded_research_data")
        raise _StopWorkflow()

    async def _ok_prereq(*args, **kwargs):
        return True, None

    monkeypatch.setattr(wf, "_execute_gradio_scripting_phase", _capture_and_stop)
    monkeypatch.setattr(wf, "check_prerequisites", _ok_prereq)
    monkeypatch.setattr(wf, "PROJECT_ROOT", tmp_path)

    wf.run_workflow_sync(
        theme="Imported Research",
        research_import_filepath=str(brief_path),
    )

    pr = captured.get("preloaded_research_data")
    assert pr is not None
    assert pr.structured_facts is None, (
        "structured_facts 不在の brief は ResearchResult.structured_facts=None として届くべき "
        "（後方互換: Phase 3 が trigger されず FactExtractor 経路を通る）"
    )
