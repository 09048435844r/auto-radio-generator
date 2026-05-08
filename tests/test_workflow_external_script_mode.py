"""run_workflow_sync の external_script_path 経路 + _generate_youtube_metadata の external_metadata 経路のテスト

Step 3 外部台本モード化の commit 5。Phase 1 + Phase 2 を完全 bypass し、Phase 3
(production) にそのまま渡せること、_generate_youtube_metadata が Gemini API を
完全に呼ばずに dict をそのまま採用することを担保する。
"""
import json
import re
from pathlib import Path

import pytest

import workflow as wf


WORKFLOW_SRC_PATH = Path(__file__).resolve().parent.parent / "workflow.py"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "verified_script_sample.json"


# ---------------------------------------------------------------------------
# (1) 構造的契約: run_workflow_sync に external_script_path 引数が追加されている
# ---------------------------------------------------------------------------

def test_run_workflow_sync_accepts_external_script_path():
    import inspect
    sig = inspect.signature(wf.run_workflow_sync)
    params = list(sig.parameters.keys())
    assert "external_script_path" in params, (
        "run_workflow_sync に external_script_path が引数として追加されていない"
    )
    # 既定値は None で後方互換 (省略時は従来通り)
    assert sig.parameters["external_script_path"].default is None


# ---------------------------------------------------------------------------
# (2) 構造的契約: 新分岐が research_import 分岐の直後に挿入されている
# ---------------------------------------------------------------------------

def test_external_script_branch_is_after_research_import():
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")
    # research_import_filepath 分岐より後に external_mode 分岐が出現
    research_pos = src.find("if research_import_filepath and not config.yaml.dev.mock_mode:")
    external_pos = src.find("if external_mode and not config.yaml.dev.mock_mode:")
    assert research_pos > 0, "research_import 分岐が見つからない"
    assert external_pos > 0, "external_mode 分岐が見つからない (新 phase 呼び出し箇所)"
    assert external_pos > research_pos, (
        "external_mode 分岐は research_import 分岐の後に来るべき (実装プラン B.2.2 通り)"
    )


# ---------------------------------------------------------------------------
# (3) 構造的契約: Phase 2 (scripting) 全体が `if not external_mode:` でガードされている
# ---------------------------------------------------------------------------

def test_phase2_guarded_by_external_mode_check():
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")
    # Phase 2 ヘッダの直後に `if not external_mode:` がある
    pattern = (
        r"#\s*=+\s*Phase\s*2:\s*台本作成.*?\n"
        r"\s*#\s*外部台本モードでは\s*Phase\s*2.*?\n"
        r"\s*if\s+not\s+external_mode:"
    )
    m = re.search(pattern, src, re.DOTALL)
    assert m is not None, (
        "Phase 2 ヘッダ直後に `if not external_mode:` ガードが見当たらない。"
        "外部台本モードでは Phase 2 全体を bypass する必要がある (実装プラン B.2.2)"
    )


# ---------------------------------------------------------------------------
# (4) _generate_youtube_metadata の external_metadata 経路: Gemini API を一切呼ばない
# ---------------------------------------------------------------------------

def test_generate_youtube_metadata_external_path_skips_llm(tmp_path: Path, monkeypatch):
    """external_metadata が dict のとき、Gemini packaging prompt を呼ばずに直接 metadata.txt を書く"""
    from core.models.script import DialogueTurn, Script, TurnType

    # Gemini クライアント生成が呼ばれたら例外を投げる ("呼ばれていない" を担保)
    def _fail_if_called(*args, **kwargs):
        raise RuntimeError("create_script_generator は外部モードで呼ばれてはいけない")

    monkeypatch.setattr(wf, "create_script_generator", _fail_if_called)

    # 最低限の Script (sections min_length=10)
    turns = [
        DialogueTurn(speaker="A", text=f"line{i}", turn_type=TurnType.DIALOGUE)
        for i in range(10)
    ]
    script = Script(
        title="ext_title", thumbnail_title="ext_th", sections=turns,
    )

    out = tmp_path / "metadata.txt"
    ext_md = {
        "title": "外部タイトル",
        "thumbnail_title": "外部短縮",
        "description": "外部の長めの概要文。" * 10,
        "hashtags": ["#a", "#b", "#c"],
    }
    result = wf._generate_youtube_metadata(
        script=script,
        chapters=[],
        output_path=out,
        theme="t",
        provider="gemini",
        external_metadata=ext_md,
    )

    # metadata dict が外部由来の値そのまま
    assert result["title"] == "外部タイトル"
    assert result["thumbnail_title"] == "外部短縮"
    assert "外部の長めの概要文" in result["description"]

    # ファイル出力されている + 「外部台本モード」の文字列が含まれる
    text = out.read_text(encoding="utf-8")
    assert "外部台本モード" in text
    assert "外部タイトル" in text

    # video_metadata.json も生成されている
    json_path = out.parent / "video_metadata.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["title"] == "外部タイトル"


# ---------------------------------------------------------------------------
# (5) 構造的契約: 旧経路は external_metadata=None で従来動作
# ---------------------------------------------------------------------------

def test_generate_youtube_metadata_passes_external_metadata_to_external_branch():
    """workflow.py 内の _generate_youtube_metadata 呼び出しに external_metadata=ext_metadata_for_packaging
    が渡されている (外部モード時の bypass を担保)"""
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")
    # 呼び出し前に ext_metadata_for_packaging が組み立てられている
    assert "ext_metadata_for_packaging = (" in src, (
        "外部モード時の事前構築 metadata 変数 ext_metadata_for_packaging が見当たらない"
    )
    assert "external_metadata=ext_metadata_for_packaging" in src, (
        "_generate_youtube_metadata の呼び出しに external_metadata 引数が渡されていない"
    )
