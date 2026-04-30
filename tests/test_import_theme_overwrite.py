"""リサーチインポート時の theme 上書きバグ回帰テスト (PR-I 同系統)

UI から `research_import_filepath` を指定して動画生成を実行すると、
app.py 側で theme 未入力時に `"Imported Research"` という placeholder が
セットされ、それが ScriptOrchestrator / MetadataGenerator まで流れて
LLM が「輸入された研究」と誤解釈するハルシネーションを発生させていた。

修正: workflow.run_workflow_sync の `_run_phases` で `nonlocal theme` を
宣言し、ResearchBrief のロード成功時に `brief.theme` で上書きする。
ResearchBrief が当該リサーチデータの SSOT であるという PR-I の方針に
合わせる。

このテストは将来のリファクタで以下が崩れないことを担保する:
- `_run_phases` 内に `nonlocal theme` 宣言が存在する
- インポート成功ブロック内で `theme = brief.theme` パターンが実行される
- 動作レベルで brief.theme が下流フェーズに伝播する
"""
import inspect
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.interfaces import ResearchResult
from core.models.artifacts import ResearchBrief
import workflow as wf


WORKFLOW_SRC_PATH = Path(__file__).resolve().parent.parent / "workflow.py"


# ---------------------------------------------------------------------------
# (1) 構造的契約: _run_phases に nonlocal theme 宣言があり、
#                   インポート分岐内で theme が brief.theme で上書きされる
# ---------------------------------------------------------------------------

def test_run_phases_declares_nonlocal_theme():
    """`_run_phases` クロージャ内で nonlocal theme 宣言があること。

    これが無いと内部での `theme = brief.theme` 代入が「ローカル変数の作成」と
    解釈され、外側スコープの theme は変わらないため修正が機能しない。
    """
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")

    # `async def _run_phases():` の本体を抽出
    m = re.search(
        r"async def _run_phases\(\):\n(?P<body>(?:[ \t].*\n|\n)+?)"
        r"(?=\n[ ]{0,4}\S|\Z)",
        src,
    )
    assert m is not None, "_run_phases 関数が見つからない（リネームされた？）"

    body = m.group("body")
    assert "nonlocal theme" in body, (
        "PR-I 同系統: _run_phases には nonlocal theme 宣言が必要。"
        "これが無いと brief.theme による上書きがクロージャに反映されない。"
    )


def test_import_block_overrides_theme_with_brief_theme():
    """インポート成功ブロックに `theme = brief.theme` 代入が存在する。"""
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")

    assert "theme = brief.theme" in src, (
        "PR-I 同系統: インポート経路で brief.theme を SSOT として "
        "workflow の theme に代入する必要がある"
    )

    # 代入が `if research_import_filepath` 以下のインポート分岐内にあること
    import_block_match = re.search(
        r"if research_import_filepath and not config\.yaml\.dev\.mock_mode:"
        r"(?P<body>(?:.|\n)+?)(?=\n[ ]{12}#\s*=+|\n[ ]{12}# Phase)",
        src,
    )
    assert import_block_match is not None, (
        "research_import_filepath 分岐ブロックが見つからない（構造変更？）"
    )
    assert "theme = brief.theme" in import_block_match.group("body"), (
        "theme 上書きはインポート分岐の内側で行うべき "
        "（外側だと通常実行時にも theme が変わってしまう）"
    )


def test_import_block_guards_empty_brief_theme():
    """brief.theme が空文字列の場合は上書きしないガードがある。"""
    src = WORKFLOW_SRC_PATH.read_text(encoding="utf-8")
    # `if brief.theme` 系のガードが上書きの直前にあること
    assert re.search(
        r"if brief\.theme[^\n]*:\s*\n(?:[^\n]*\n){0,5}?\s*theme = brief\.theme",
        src,
    ), (
        "brief.theme が空でも上書きしてしまうと、誤って空テーマを下流に流す。"
        "上書き直前に `if brief.theme[.strip()]` のガードが必要。"
    )


# ---------------------------------------------------------------------------
# (2) 動作レベル: run_workflow_sync で brief.theme が下流フェーズに伝播する
# ---------------------------------------------------------------------------

def _write_brief_json(path: Path, theme: str) -> Path:
    brief = ResearchBrief(
        session_id="20260501_120000",
        theme=theme,
        research_mode="lecture",
        research_content="テスト用リサーチ本文。" * 30,
        research_sources=[],
        queries=["クエリ1", "クエリ2"],
        angle="テスト切り口",
    )
    brief_path = path / "research_brief.json"
    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")
    return brief_path


class _StopWorkflow(Exception):
    """テスト用センチネル: スクリプト生成段階に到達したら捕捉する"""


def test_imported_brief_theme_propagates_to_scripting_phase(tmp_path, monkeypatch):
    """インポート時に brief.theme がスクリプト生成フェーズへ正しく伝播する。

    app.py が placeholder "Imported Research" を渡しても、
    workflow.py の import block が brief.theme で上書きするため、
    `_execute_gradio_scripting_phase` の theme 引数は brief.theme に等しいはず。
    """
    expected_theme = "NVIDIA Syncアプリの使い方と機能解説"
    brief_path = _write_brief_json(tmp_path, expected_theme)

    captured: dict = {}

    async def _capture_and_stop(*args, **kwargs):
        captured["theme"] = kwargs.get("theme")
        raise _StopWorkflow("captured theme; aborting downstream phases for test")

    async def _ok_prereq(*args, **kwargs):
        return True, None

    monkeypatch.setattr(wf, "_execute_gradio_scripting_phase", _capture_and_stop)
    monkeypatch.setattr(wf, "check_prerequisites", _ok_prereq)

    # output_dir を tmp 配下に強制（テスト分離）
    monkeypatch.setattr(wf, "PROJECT_ROOT", tmp_path)

    result = wf.run_workflow_sync(
        theme="Imported Research",  # app.py が入れる placeholder を再現
        research_import_filepath=str(brief_path),
    )

    # _StopWorkflow は workflow 内の except でキャッチされ failure 結果になる
    assert "theme" in captured, (
        f"_execute_gradio_scripting_phase が呼ばれなかった。result={result}"
    )
    assert captured["theme"] == expected_theme, (
        f"インポート経路で brief.theme が伝播していない。"
        f"期待: {expected_theme!r} / 実際: {captured['theme']!r}"
    )


def test_user_theme_is_overwritten_by_brief_theme_when_importing(tmp_path, monkeypatch):
    """インポート経路では brief を SSOT とし、ユーザ入力 theme よりも優先する。

    PR-I の方針に合わせる: ResearchBrief は当該リサーチデータの SSOT。
    インポート時にユーザが別 theme を打ち込んでも、ロード成功時は brief.theme を採用。
    （これは将来 UX として変更可能だが、現時点では SSOT 一貫性を優先）
    """
    brief_theme = "ResearchBrief の本来のテーマ"
    user_theme = "ユーザが UI に打ち込んだ別のテーマ"
    brief_path = _write_brief_json(tmp_path, brief_theme)

    captured: dict = {}

    async def _capture_and_stop(*args, **kwargs):
        captured["theme"] = kwargs.get("theme")
        raise _StopWorkflow()

    async def _ok_prereq(*args, **kwargs):
        return True, None

    monkeypatch.setattr(wf, "_execute_gradio_scripting_phase", _capture_and_stop)
    monkeypatch.setattr(wf, "check_prerequisites", _ok_prereq)
    monkeypatch.setattr(wf, "PROJECT_ROOT", tmp_path)

    wf.run_workflow_sync(
        theme=user_theme,
        research_import_filepath=str(brief_path),
    )

    assert captured.get("theme") == brief_theme, (
        f"インポート時はユーザ入力 theme より brief.theme を優先すべき。"
        f"期待: {brief_theme!r} / 実際: {captured.get('theme')!r}"
    )


def test_no_import_filepath_keeps_user_theme(tmp_path, monkeypatch):
    """インポートを使わない通常経路では theme は上書きされない（回帰防止）。"""
    user_theme = "通常実行時のユーザテーマ"

    captured: dict = {}

    async def _capture_and_stop(*args, **kwargs):
        captured["theme"] = kwargs.get("theme")
        raise _StopWorkflow()

    async def _ok_prereq(*args, **kwargs):
        return True, None

    # Planning phase もインターセプトする（インポートなしでは Planning が先に呼ばれる）
    async def _fake_planning(*args, **kwargs):
        captured.setdefault("theme", kwargs.get("theme"))
        raise _StopWorkflow()

    monkeypatch.setattr(wf, "_execute_gradio_scripting_phase", _capture_and_stop)
    monkeypatch.setattr(wf, "execute_planning_phase", _fake_planning)
    monkeypatch.setattr(wf, "check_prerequisites", _ok_prereq)
    monkeypatch.setattr(wf, "PROJECT_ROOT", tmp_path)

    # research_mode 設定が必須なので overrides 経由で渡す
    # ResearchMode は Literal なのでリテラル文字列を直接指定
    from workflow import UIOverrides

    wf.run_workflow_sync(
        theme=user_theme,
        overrides=UIOverrides(
            research_mode="lecture",
            enable_research=True,
            llm_provider="gemini",
        ),
        research_import_filepath=None,
    )

    assert captured.get("theme") == user_theme, (
        f"通常実行時に theme が予期せず変わった: "
        f"期待: {user_theme!r} / 実際: {captured.get('theme')!r}"
    )


# ---------------------------------------------------------------------------
# (3) ResearchBrief は SSOT 契約: brief.theme フィールドが存在する
# ---------------------------------------------------------------------------

def test_research_brief_has_theme_field():
    """ResearchBrief.theme が定義されている（前提条件）。"""
    fields = ResearchBrief.model_fields
    assert "theme" in fields, "ResearchBrief.theme が削除されている"
    assert fields["theme"].is_required(), "ResearchBrief.theme は必須"
