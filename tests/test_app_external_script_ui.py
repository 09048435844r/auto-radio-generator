"""app.py の外部台本モード UI 構造テスト

Step 3 外部台本モード化の commit 6。app.py に追加した「🎬 外部台本モード」
アコーディオンと、旧 LLM 経路の Deprecated アコーディオン化が source-level で
維持されることを担保する。Gradio UI そのものを起動するテストではなく、
リスク #4 (UI ハンドラ配線維持) は別途手動 smoke test で確認する方針。
"""
import re
from pathlib import Path


APP_PY_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_app_has_external_script_accordion_open_by_default():
    """外部台本モードアコーディオンが open=True (default open) で配置されている"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    pattern = (
        r'gr\.Accordion\(\s*'
        r'"🎬 外部台本モード（推奨 / VerifiedScript JSON）",\s*'
        r'open=True\s*\)'
    )
    assert re.search(pattern, src), (
        "app.py に「🎬 外部台本モード（推奨 / VerifiedScript JSON）」open=True の Accordion が見当たらない"
    )


def test_app_has_verified_script_file_picker():
    """verified_script_file というファイルピッカーが定義されている"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    assert "verified_script_file = gr.File(" in src, (
        "verified_script_file ファイルピッカーが定義されていない"
    )


def test_app_perplexity_options_accordion_replaces_deprecated_accordion():
    """Step 4 v2 (2026-05-10): 旧 LLM 経路 Deprecated アコーディオンは物理削除済み。
    代わりに 'Perplexity リサーチオプション' アコーディオンに theme_input /
    research_mode_dropdown / avoid_topics_input / research_import_file が含まれる
    （research_only ベンチマーク + research_brief.json インポート用）。"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    # 旧 Deprecated アコーディオンが残っていないこと
    assert "Deprecated: v2 で削除予定" not in src, (
        "Step 4 v2 で削除されるべき Deprecated アコーディオンの文字列が残っている"
    )

    # 新 Perplexity リサーチオプション アコーディオンが存在
    perp_match = re.search(
        r'gr\.Accordion\(\s*\n?\s*"🔍 Perplexity リサーチオプション',
        src,
    )
    assert perp_match, "新 Perplexity リサーチオプション アコーディオンが見当たらない"

    rest = src[perp_match.start():]
    assert "theme_input = gr.Textbox(" in rest
    assert "research_mode_dropdown = gr.Dropdown(" in rest
    assert "avoid_topics_input = gr.Textbox(" in rest
    assert "research_import_file = gr.File(" in rest


def test_app_gemini_only_components_removed():
    """Step 4 v2: Gemini auto path 専用 UI コンポーネントが削除されている"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    # 削除確認
    assert "llm_provider_dropdown" not in src, "llm_provider_dropdown が残存"
    assert "second_mode_dropdown" not in src, "second_mode_dropdown が残存"
    assert "jingle_dropdown" not in src, "jingle_dropdown が残存"
    assert "jingle_path_input" not in src, "jingle_path_input が残存"


def test_app_registers_verified_script_file_in_components_dict():
    """generator_components dict に verified_script_file が登録されている"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    assert '"verified_script_file": verified_script_file,' in src, (
        "generator_components dict に verified_script_file キーが追加されていない"
    )


def test_app_passes_external_script_path_to_run_workflow_sync():
    """generate_video が run_workflow_sync に external_script_path を渡している"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    assert "external_script_path=verified_script_filepath or None," in src, (
        "run_workflow_sync 呼び出しに external_script_path 引数が渡されていない"
    )


def test_app_event_handler_inputs_include_verified_script_file():
    """generate_video のイベントハンドラ inputs に verified_script_file が含まれる"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    # research_import_file の直後に verified_script_file が並ぶ構造
    pattern = (
        r'generator_components\["research_import_file"\],\s*\n'
        r'\s*generator_components\["verified_script_file"\],'
    )
    assert re.search(pattern, src), (
        "イベントハンドラの inputs に verified_script_file が追加されていない"
    )


def test_app_existing_research_import_components_preserved():
    """旧 research_import_file コンポーネントは削除/改名されず維持される (handler 配線維持)"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    assert "research_import_file = gr.File(" in src
    assert '"research_import_file": research_import_file,' in src


def test_app_input_validation_accepts_external_script_without_theme():
    """Step 4 v2: 外部台本モード または mock または research_import のいずれかが必須。
    テーマだけでは生成不可（旧 Gemini 自動経路は削除済み）。"""
    src = APP_PY_PATH.read_text(encoding="utf-8")
    assert "and not verified_script_filepath" in src, (
        "外部台本モードガード `and not verified_script_filepath` が見当たらない"
    )
