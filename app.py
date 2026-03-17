"""自動ラジオ動画生成システム - Gradio Web UI

ブラウザ上でパラメータ調整と動画生成実行ができるWeb UIアプリケーション

v3.3.2 機能:
- タブ式UI: 自動生成とマニュアル制作を分離
- マニュアル制作ワークフロー: Step A(台本) → Step B(音声) → Step C(動画)
- 設定の永続化: ユーザー設定を自動保存・復元
- APIヘルスチェック: 生成前に接続状態を確認
- 第2部モード: 1つのテーマで2部構成のラジオ番組を生成
- 処理ログ出力: 各実行の詳細ログをファイルに保存

コア機能:
- Perplexityによるテーマのリサーチ（4モード: ディベート/世間の声/トリビア/週次ダイジェスト）
- Geminiによる3部構成の台本生成（本題70%/リスナーメール20%/エンディング10%）
- VOICEVOXによる音声合成
- FFmpegによる動画生成（音声スペクトラム可視化対応）
"""
import sys
from pathlib import Path
from typing import Optional

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr
from workflow import UIOverrides, run_workflow_sync, WorkflowResult, scan_assets, create_script_generator, load_config, ThumbnailRegenerationState
from core.models import Script
from core.interfaces import ResearchResult
from core.settings_manager import SettingsManager
from services.research import PerplexityResearcher
from services.script_generation import GeminiClient
from services.media_processing import ThumbnailGenerator
from google.genai import types
import json
import os
import socket
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from urllib.parse import urlparse
import asyncio


# デフォルトジングル設定
DEFAULT_JINGLES = {
    "デフォルト": "assets/jingles/default.mp3",
    "明るい": "assets/jingles/bright.mp3",
    "シリアス": "assets/jingles/serious.mp3",
    "クール": "assets/jingles/cool.mp3",
}


def resolve_jingle_path(jingle_choice: str, custom_path: str = "") -> Optional[str]:
    """ジングル選択に基づいてファイルパスを解決"""
    if jingle_choice == "なし" or jingle_choice == "":
        return None
    elif jingle_choice == "カスタムファイル":
        if custom_path and Path(custom_path).exists():
            return custom_path
        else:
            return None
    elif jingle_choice in DEFAULT_JINGLES:
        default_path = PROJECT_ROOT / DEFAULT_JINGLES[jingle_choice]
        return str(default_path) if default_path.exists() else None
    else:
        return None


def toggle_jingle_path_visibility(jingle_choice: str) -> str:
    """ジングルパス入力の表示/非表示を切り替え"""
    return gr.update(visible=(jingle_choice == "カスタムファイル"))


async def check_api_health() -> tuple[str, str]:
    """Check API health for Gemini and Perplexity with actual models from config"""
    config = load_config()
    
    gemini_status = "🟡チェック中..."
    perplexity_status = "🟡チェック中..."
    
    try:
        # Gemini health check
        gemini_client = GeminiClient(config)
        try:
            # Use minimal request with timeout
            response = gemini_client.client.models.generate_content(
                model=gemini_client.model_name,
                contents="ping",
                config=types.GenerateContentConfig(
                    max_output_tokens=1,
                    temperature=0.1
                )
            )
            gemini_status = f"🟢OK ({gemini_client.model_name})"
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                gemini_status = f"🔴Error (401認証)"
            elif "429" in error_str:
                gemini_status = f"🔴Error (429制限)"
            else:
                gemini_status = f"🔴Error ({gemini_client.model_name})"
    except Exception as e:
        gemini_status = "🔴Error (初期化失敗)"
    
    try:
        # Perplexity health check
        perplexity_client = PerplexityResearcher(config)
        try:
            # Use minimal request with timeout
            response = perplexity_client.client.chat.completions.create(
                model=perplexity_client.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                timeout=5
            )
            perplexity_status = f"🟢OK ({perplexity_client.model})"
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                perplexity_status = f"🔴Error (401認証)"
            elif "429" in error_str:
                perplexity_status = f"🔴Error (429制限)"
            else:
                perplexity_status = f"🔴Error ({perplexity_client.model})"
    except Exception as e:
        perplexity_status = "🔴Error (初期化失敗)"
    
    return gemini_status, perplexity_status


def run_api_health_check():
    """Wrapper for async health check to run in event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(check_api_health())
    finally:
        loop.close()


# ログメッセージを蓄積するためのグローバル変数
_log_messages: list[str] = []

# 設定マネージャー
_settings_manager = SettingsManager()

# カスタムCSS定義（Gradio 6.0対応: launch()で使用）
CUSTOM_CSS = """
/* 全体のフォントと背景 */
.gradio-container { 
    font-family: 'Helvetica Neue', Arial, sans-serif; 
}

/* カード風のスタイル */
.group-container {
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
    background-color: #f9fafb;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.dark .group-container {
    background-color: #1f2937;
    border-color: #374151;
}

/* 強調ボタン */
.primary-btn { 
    font-weight: bold; 
    font-size: 1.1em; 
}

/* ギャラリーの角丸 */
.gallery-container {
    border-radius: 8px;
    overflow: hidden;
}
"""


def clear_logs() -> None:
    """ログをクリア"""
    global _log_messages
    _log_messages = []


def append_log(msg: str) -> None:
    """ログを追加"""
    global _log_messages
    _log_messages.append(msg)


def get_logs() -> str:
    """ログを取得"""
    return "\n".join(_log_messages)


# リサーチモードのマッピング
RESEARCH_MODE_MAP = {
    "ディベート (賛否両論)": "debate",
    "世間の声 (SNS反応)": "voices",
    "トリビア (雑学)": "trivia",
    "今週のまとめ (ニュース)": "weekly_digest",
    "解説・講座 (Lecture)": "lecture",
    "リサーチなし": None
}


def get_asset_choices() -> dict[str, list[str]]:
    """アセットの選択肢を取得"""
    assets = scan_assets(PROJECT_ROOT)
    return assets


def get_background_gallery_images() -> list[str]:
    """背景画像ギャラリー用の画像パスリストを取得"""
    backgrounds_dir = PROJECT_ROOT / "assets" / "backgrounds"
    if not backgrounds_dir.exists():
        return []
    
    image_paths = []
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        image_paths.extend(backgrounds_dir.glob(f"*{ext}"))
    
    return [str(p) for p in sorted(image_paths)]


def get_background_image_path(filename: str) -> str | None:
    """背景画像のファイル名から絶対パスを取得"""
    if not filename:
        return None
    backgrounds_dir = PROJECT_ROOT / "assets" / "backgrounds"
    image_path = backgrounds_dir / filename
    return str(image_path) if image_path.exists() else None


def handle_gallery_select(evt: gr.SelectData) -> tuple[str, str]:
    """ギャラリーから画像を選択したときの処理
    
    Args:
        evt: Gradioの選択イベント
    
    Returns:
        (画像パス, ファイル名)
    """
    if evt.value and 'image' in evt.value:
        image_path = evt.value['image']['path']
        filename = Path(image_path).name
        return image_path, filename
    return None, ""


def handle_custom_upload(file_path: str) -> tuple[str, str]:
    """カスタム画像をアップロードしたときの処理
    
    Args:
        file_path: アップロードされたファイルのパス
    
    Returns:
        (画像パス, ファイル名)
    """
    if file_path:
        filename = Path(file_path).name
        return file_path, filename
    return None, ""


def load_initial_background(filename: str) -> str | None:
    """初期背景画像を読み込む
    
    Args:
        filename: 背景画像のファイル名
    
    Returns:
        画像パス
    """
    return get_background_image_path(filename)


def create_step_mode_ui(assets: dict) -> dict:
    """こだわりステップモードのUI構築
    
    Args:
        assets: アセット情報（背景画像、BGMリスト）
    
    Returns:
        UIコンポーネントの辞書
    """
    components = {}
    
    with gr.Accordion("🛠 こだわりステップモード (上級者向け)", open=False):
        gr.Markdown("""
        **高度な制作モード** - 各ステップを個別に実行・調整できます
        
        🔹 **Step 0**: 企画 → 検索クエリ案を生成  
        🔹 **Step 1**: リサーチ & 台本 → クエリでリサーチし台本を作成  
        🔹 **Step 2**: 制作 → 台本から動画を生成
        """)
        
        # ========== Step 0: 企画フェーズ ==========
        gr.Markdown("---")
        gr.Markdown("### 📋 Step 0: 企画 (Planning)")
        
        with gr.Row():
            components["step0_theme"] = gr.Textbox(
                label="テーマ",
                placeholder="例: 量子コンピュータの最新動向",
                lines=2,
                scale=3
            )
            components["step0_mode"] = gr.Dropdown(
                label="リサーチモード",
                choices=list(RESEARCH_MODE_MAP.keys()),
                value="トリビア (雑学)",
                scale=1
            )
        
        components["step0_execute_btn"] = gr.Button(
            "📋 Step 0: 企画・クエリ案出し",
            variant="primary",
            size="lg"
        )
        
        gr.Markdown("**生成されたクエリ案:**")
        with gr.Row():
            components["step0_query1"] = gr.Textbox(label="クエリ1", lines=2, interactive=True)
            components["step0_query2"] = gr.Textbox(label="クエリ2", lines=2, interactive=True)
            components["step0_query3"] = gr.Textbox(label="クエリ3", lines=2, interactive=True)
        
        components["step0_angle"] = gr.Textbox(
            label="切り口・コンセプト",
            lines=2,
            interactive=True
        )
        
        # ========== Step 1: リサーチ & 台本フェーズ ==========
        gr.Markdown("---")
        gr.Markdown("### 🔍 Step 1: リサーチ & 台本 (Research & Scripting)")
        
        gr.Markdown("**使用するクエリ（Step 0から自動入力 or 手動編集）:**")
        with gr.Row():
            components["step1_query1"] = gr.Textbox(label="クエリ1", lines=2, interactive=True)
            components["step1_query2"] = gr.Textbox(label="クエリ2", lines=2, interactive=True)
            components["step1_query3"] = gr.Textbox(label="クエリ3", lines=2, interactive=True)
        
        components["step1_excluded_topics"] = gr.Textbox(
            label="既出情報の除外",
            placeholder="例: 前回の動画で話した内容、避けたい話題など",
            lines=3,
            info="この情報は台本生成時に考慮されます（オプション）"
        )
        
        components["step1_execute_btn"] = gr.Button(
            "🔍 Step 1: 上記クエリで台本を作成",
            variant="primary",
            size="lg"
        )
        
        gr.Markdown("**生成された台本:**")
        components["step1_title"] = gr.Textbox(
            label="タイトル",
            lines=1,
            interactive=True
        )
        components["step1_thumbnail"] = gr.Textbox(
            label="サムネイル文字",
            lines=1,
            interactive=True
        )
        components["step1_description"] = gr.Textbox(
            label="概要欄",
            lines=5,
            interactive=True
        )
        components["step1_script_json"] = gr.Code(
            label="台本JSON (編集可能)",
            language="json",
            lines=15,
            interactive=True
        )
        
        components["step1_log"] = gr.Textbox(
            label="処理ログ",
            lines=8,
            interactive=False
        )
        
        # ========== Step 2: 制作フェーズ ==========
        gr.Markdown("---")
        gr.Markdown("### 🎬 Step 2: 制作 (Production)")
        
        gr.Markdown("**動画設定:**")
        with gr.Row():
            components["step2_background"] = gr.Dropdown(
                label="背景画像",
                choices=assets.get("backgrounds", ["default.png"]),
                value=assets.get("backgrounds", ["default.png"])[0] if assets.get("backgrounds") else None
            )
            components["step2_bgm"] = gr.Dropdown(
                label="BGM",
                choices=assets.get("bgm", ["default.mp3"]),
                value=assets.get("bgm", ["default.mp3"])[0] if assets.get("bgm") else None
            )
        
        with gr.Row():
            components["step2_bgm_volume"] = gr.Slider(
                label="BGM音量",
                minimum=0.0,
                maximum=0.5,
                value=0.15,
                step=0.01
            )
            components["step2_speed"] = gr.Slider(
                label="話速",
                minimum=0.8,
                maximum=1.5,
                value=1.0,
                step=0.05
            )
        
        components["step2_spectrum"] = gr.Checkbox(
            label="音声スペクトラムを表示",
            value=True
        )
        
        components["step2_execute_btn"] = gr.Button(
            "🎬 Step 2: この内容で動画を生成",
            variant="primary",
            size="lg"
        )
        
        components["step2_video"] = gr.Video(
            label="生成された動画",
            height=360
        )
        
        components["step2_log"] = gr.Textbox(
            label="処理ログ",
            lines=8,
            interactive=False
        )
    
    return components


def execute_step0_planning(
    theme: str,
    research_mode: str,
    progress=gr.Progress()
) -> tuple[str, str, str, str]:
    """Step 0: 企画フェーズを実行
    
    Args:
        theme: テーマ
        research_mode: リサーチモード
        progress: Gradio進捗バー
    
    Returns:
        (クエリ1, クエリ2, クエリ3, 切り口)
    """
    if not theme or not theme.strip():
        return "", "", "", "エラー: テーマを入力してください"
    
    mode = RESEARCH_MODE_MAP.get(research_mode)
    if not mode:
        return "", "", "", "エラー: リサーチモードを選択してください"
    
    try:
        from workflow import execute_planning_phase, ProgressCallback
        import asyncio
        
        config = load_config()
        
        # コールバック設定
        cb = ProgressCallback()
        cb.log = lambda msg: None  # ログは不要
        cb.progress = lambda ratio, desc: progress(ratio, desc=desc)
        
        # 企画フェーズを実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            execute_planning_phase(
                theme=theme.strip(),
                mode=mode,
                config=config,
                callbacks=cb
            )
        )
        loop.close()
        
        queries = result.queries
        angle = result.angle or ""
        
        return (
            queries[0] if len(queries) > 0 else "",
            queries[1] if len(queries) > 1 else "",
            queries[2] if len(queries) > 2 else "",
            angle
        )
        
    except Exception as e:
        import traceback
        error_msg = f"エラー: {str(e)}\n{traceback.format_exc()}"
        return "", "", "", error_msg


def execute_step1_scripting(
    theme: str,
    research_mode: str,
    query1: str,
    query2: str,
    query3: str,
    excluded_topics: str,
    progress=gr.Progress()
) -> tuple[str, str, str, str, str]:
    """Step 1: リサーチ & 台本フェーズを実行
    
    Args:
        theme: テーマ
        research_mode: リサーチモード
        query1, query2, query3: 検索クエリ
        excluded_topics: 除外トピック
        progress: Gradio進捗バー
    
    Returns:
        (タイトル, サムネイル文字, 概要欄, 台本JSON, ログ)
    """
    if not theme or not theme.strip():
        return "", "", "", "", "エラー: テーマを入力してください"
    
    mode = RESEARCH_MODE_MAP.get(research_mode)
    if not mode:
        return "", "", "", "", "エラー: リサーチモードを選択してください"
    
    queries = [q.strip() for q in [query1, query2, query3] if q and q.strip()]
    if not queries:
        return "", "", "", "", "エラー: 少なくとも1つのクエリを入力してください"
    
    try:
        from workflow import execute_scripting_phase, ProgressCallback
        import asyncio
        from pathlib import Path
        from datetime import datetime
        import json
        
        config = load_config()
        
        # 出力ディレクトリ
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "output" / "step_mode" / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # ログ収集
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, desc: str):
            progress(ratio, desc=desc)
        
        cb = ProgressCallback()
        cb.log = log_callback
        cb.progress = progress_callback
        
        # 台本生成フェーズを実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            execute_scripting_phase(
                theme=theme.strip(),
                mode=mode,
                queries=queries,
                config=config,
                output_dir=output_dir,
                enable_research=True,
                excluded_topics=excluded_topics.strip() if excluded_topics else None,
                callbacks=cb
            )
        )
        loop.close()
        
        script = result.script
        
        # 台本JSONを整形
        script_json = json.dumps(script.model_dump(), ensure_ascii=False, indent=2)
        
        # ログを整形
        log_text = "\n".join(log_messages)
        
        return (
            script.title or "",
            script.thumbnail_title or "",
            script.description or "",
            script_json,
            log_text
        )
        
    except Exception as e:
        import traceback
        error_msg = f"エラー: {str(e)}\n{traceback.format_exc()}"
        return "", "", "", "", error_msg


def execute_step2_production(
    title: str,
    description: str,
    script_json: str,
    background_image: str,
    bgm_file: str,
    bgm_volume: float,
    speed_scale: float,
    enable_spectrum: bool,
    progress=gr.Progress()
) -> tuple[str | None, str]:
    """Step 2: 制作フェーズを実行
    
    Args:
        title: タイトル
        description: 概要欄
        script_json: 台本JSON
        background_image: 背景画像
        bgm_file: BGMファイル
        bgm_volume: BGM音量
        speed_scale: 話速
        enable_spectrum: スペクトラム表示
        progress: Gradio進捗バー
    
    Returns:
        (動画パス, ログ)
    """
    if not script_json or not script_json.strip():
        return None, "エラー: 台本JSONを入力してください"
    
    try:
        from workflow import execute_production_phase, ProgressCallback
        import asyncio
        from pathlib import Path
        from datetime import datetime
        import json
        
        config = load_config()
        
        # 台本JSONをパース
        script_data = json.loads(script_json)
        script = Script.model_validate(script_data)
        
        # タイトルと概要欄を更新
        if title:
            script.title = title
        if description:
            script.description = description
        
        # 出力ディレクトリ
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "output" / "step_mode" / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # ログ収集
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, desc: str):
            progress(ratio, desc=desc)
        
        cb = ProgressCallback()
        cb.log = log_callback
        cb.progress = progress_callback
        
        # オーバーライド設定
        overrides = UIOverrides(
            bgm_volume=bgm_volume,
            fade_in_sec=3.0,
            fade_out_sec=3.0,
            speed_scale=speed_scale,
            enable_spectrum=enable_spectrum,
            background_image=background_image,
            bgm_file=bgm_file
        )
        
        # 制作フェーズを実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            execute_production_phase(
                script=script,
                config=config,
                output_dir=output_dir,
                overrides=overrides,
                callbacks=cb
            )
        )
        loop.close()
        
        # ログを整形
        log_text = "\n".join(log_messages)
        
        if result.video_path and result.video_path.exists():
            return str(result.video_path), log_text
        else:
            return None, log_text + "\n\nエラー: 動画ファイルが生成されませんでした"
        
    except json.JSONDecodeError as e:
        return None, f"エラー: 台本JSONのパースに失敗しました: {str(e)}"
    except Exception as e:
        import traceback
        error_msg = f"エラー: {str(e)}\n{traceback.format_exc()}"
        return None, error_msg


def generate_video(
    theme: str,
    research_mode: str,
    llm_provider: str,
    background_image: str,
    bgm_file: str,
    bgm_volume: float,
    fade_time: float,
    speed_scale: float,
    enable_spectrum: bool,
    avoid_topics: str = "",
    upload_to_youtube: bool = False,
    footer_text: str = "",
    use_mock: bool = False,
    second_mode: str = "なし",
    jingle_choice: str = "なし",
    jingle_custom_path: str = "",
    progress=gr.Progress()
) -> tuple[str | None, str, str, str, str, str, Optional[ThumbnailRegenerationState]]:
    """動画生成を実行し、サムネイル再作成用Stateも返す
    
    Args:
        theme: 動画のテーマ
        research_mode: リサーチモード
        llm_provider: LLMプロバイダー ("gemini" | "openai" | "anthropic")
        background_image: 背景画像ファイル名
        bgm_file: BGMファイル名
        bgm_volume: BGM音量 (0.0-0.5)
        fade_time: フェードイン/アウト時間 (秒)
        speed_scale: 音声スピード (0.8-1.5)
        enable_spectrum: スペクトラム表示
        avoid_topics: 避けてほしい話題（Negative Prompt）
        upload_to_youtube: YouTubeへ自動アップロードするか（UI優先）
        footer_text: 概要欄フッター文（UI入力優先）
        use_mock: Mockモードを使用するか
        second_mode: 第2部のリサーチモード
        jingle_choice: 場面転換ジングルの選択
        jingle_custom_path: カスタムジングルファイルのパス
        progress: Gradio進捗バー
    
    Returns:
        (動画パス, ログ出力, コストレポート, タイトル, 概要欄, YouTube状態, ThumbnailRegenerationState)
    """
    # 入力検証
    if (not theme or not theme.strip()) and not use_mock:
        return None, "エラー: テーマを入力してください。", "", "", "", "YouTube: 未実行"

    effective_theme = theme.strip() if theme and theme.strip() else "Mock run"
    
    # ジングルパスを解決
    jingle_path = resolve_jingle_path(jingle_choice, jingle_custom_path)
    if jingle_choice != "なし" and not jingle_path:
        append_log(f"[WARNING] ジングルファイルが見つかりません: {jingle_choice}")
    
    # ログをクリア
    clear_logs()
    append_log("自動ラジオ動画生成システム v3.3.2")
    append_log("=" * 40)
    
    if second_mode != "なし":
        append_log(f"[INFO] 第2部モード有効: {research_mode} → {second_mode}")
    if jingle_path:
        append_log(f"[INFO] ジングル有効: {jingle_choice} ({jingle_path})")
    
    # リサーチモードを変換
    mode = RESEARCH_MODE_MAP.get(research_mode)
    second_mode_enum = RESEARCH_MODE_MAP.get(second_mode) if second_mode != "なし" else None
    enable_research = mode is not None
    
    # オーバーライド設定を作成
    overrides = UIOverrides(
        research_mode=mode,
        enable_research=enable_research,
        llm_provider=llm_provider,
        bgm_volume=bgm_volume,
        fade_in_sec=fade_time,
        fade_out_sec=fade_time,
        speed_scale=speed_scale,
        enable_spectrum=enable_spectrum,
        background_image=background_image,
        bgm_file=bgm_file
    )
    
    # 進捗表示用コールバック
    def log_callback(msg: str):
        append_log(msg)
    
    def progress_callback(ratio: float, desc: str):
        progress(ratio, desc=desc)

    if use_mock and upload_to_youtube:
        append_log("[INFO] Mockモード実行のため、YouTubeアップロード設定は無効化されます")
    
    # ワークフロー実行
    result: WorkflowResult = run_workflow_sync(
        theme=effective_theme,
        overrides=overrides,
        log_callback=log_callback,
        progress_callback=progress_callback,
        use_mock=use_mock,
        avoid_topics=avoid_topics if avoid_topics and avoid_topics.strip() else None,
        upload_override=upload_to_youtube,
        footer_text_override=footer_text,
        second_mode=second_mode_enum,
        jingle_path=jingle_path,
    )
    
    # 成功時に設定を保存とState作成
    if result.success:
        _settings_manager.update_from_ui(
            research_mode=research_mode,
            background_image=background_image,
            bgm_file=bgm_file,
            bgm_volume=bgm_volume,
            fade_time=fade_time,
            speed_scale=speed_scale,
            enable_spectrum=enable_spectrum
        )
        
        # サムネイル再作成用Stateを作成
        if result.output_dir and result.script:
            # 台本要約を生成
            script_summary = ""
            if result.script.dialogue:
                dialogues = result.script.get_dialogue_only()
                dialogue_texts = [d.text for d in dialogues[:10]]
                script_summary = " ".join(dialogue_texts)[:200] + "..." if len(" ".join(dialogue_texts)) > 200 else " ".join(dialogue_texts)
            
            # 背景画像パスを解決
            config = load_config()
            bg_path = config.yaml.paths.background_image
            if background_image and background_image != "default.png":
                bg_path = f"assets/backgrounds/{background_image}"
            
            thumbnail_state = ThumbnailRegenerationState(
                theme=theme,
                script_summary=script_summary,
                output_dir=str(result.output_dir),
                background_path=bg_path,
                base_title=result.formatted_title or theme,
                generation_count=0
            )
        else:
            thumbnail_state = None
    else:
        thumbnail_state = None
    
    # 結果を返す
    if result.success and result.video_path:
        append_log("")
        append_log("🎉 動画生成が完了しました！")
        append_log(f"出力: {result.video_path}")
        append_log(f"長さ: {result.duration_sec:.1f}秒")
        append_log(f"サイズ: {result.file_size_mb:.1f}MB")
        if result.script:
            append_log(f"タイトル: {result.script.title}")
        
        # コストレポートとメタデータ
        cost_report = result.cost_report if result.cost_report else ""
        formatted_title = result.formatted_title if result.formatted_title else ""
        formatted_description = result.formatted_description if result.formatted_description else ""
        if result.uploaded_video_url:
            youtube_status = f"✅ YouTube: [公開リンクを開く]({result.uploaded_video_url})"
        else:
            youtube_status = "YouTube: 未実行"
        
        return (
            str(result.video_path),
            get_logs(),
            cost_report,
            formatted_title,
            formatted_description,
            youtube_status,
            thumbnail_state,
        )
    else:
        error_msg = result.error_message if result.error_message else "動画生成に失敗しました"
        append_log(f"\n❌ {error_msg}")
        return None, get_logs(), "", "", "", "YouTube: 未実行", None


def generate_video_mock(
    theme: str,
    research_mode: str,
    llm_provider: str,
    background_image: str,
    bgm_file: str,
    bgm_volume: float,
    fade_time: float,
    speed_scale: float,
    enable_spectrum: bool,
    avoid_topics: str = "",
    upload_to_youtube: bool = False,
    footer_text: str = "",
    second_mode: str = "なし",
    jingle_choice: str = "なし",
    jingle_custom_path: str = "",
    progress=gr.Progress()
) -> tuple[str | None, str, str, str, str, str, Optional[ThumbnailRegenerationState]]:
    return generate_video(
        theme=theme,
        research_mode=research_mode,
        llm_provider=llm_provider,
        background_image=background_image,
        bgm_file=bgm_file,
        bgm_volume=bgm_volume,
        fade_time=fade_time,
        speed_scale=speed_scale,
        enable_spectrum=enable_spectrum,
        use_mock=True,
        avoid_topics=avoid_topics,
        upload_to_youtube=upload_to_youtube,
        footer_text=footer_text,
        second_mode=second_mode,
        jingle_choice=jingle_choice,
        jingle_custom_path=jingle_custom_path,
        progress=progress,
    )


def generate_script_only(
    theme: str,
    research_mode: str,
    progress=gr.Progress()
) -> tuple[str, str]:
    """台本のみを生成してマニュアルタブに転送
    
    AIプロデューサー機能を使用した3ステッププロセス:
    Step 0: AIが検索計画を作成
    Step 1: 複数クエリで並列リサーチ
    Step 2: 収集した情報を元に台本生成
    
    Args:
        theme: 動画のテーマ
        research_mode: リサーチモード
        progress: Gradio進捗バー
    
    Returns:
        (台本JSON, ログ出力)
    """
    import asyncio
    from services.research import PerplexityResearcher
    from services.script_generation import GeminiClient
    
    # ログをクリア
    clear_logs()
    append_log("🎬 AIプロデューサーモード")
    append_log("=" * 40)
    append_log("多角的深掘り検索で台本を生成します")
    
    # 入力検証
    if not theme or not theme.strip():
        return "", "エラー: テーマを入力してください。"
    
    try:
        # 設定読み込み
        config = load_config(PROJECT_ROOT)
        
        # リサーチモードを変換
        mode = RESEARCH_MODE_MAP.get(research_mode)
        
        async def generate():
            # Step 0: AIプロデューサーが検索計画を作成
            research_result = None
            script_generator = None
            
            if mode:
                progress(0.1, desc="Step 0: AIが検索計画を作成中...")
                append_log(f"\n== Step 0: 検索計画作成 ==")
                append_log(f"テーマ: {theme.strip()}")
                
                script_generator = GeminiClient(config)
                plan = await script_generator.create_research_plan(theme.strip(), mode, instruction=None)
                
                append_log(f"\n✓ 検索計画作成完了")
                append_log(f"切り口: {plan.angle}")
                append_log(f"\n検索クエリ:")
                for i, q in enumerate(plan.queries, 1):
                    append_log(f"  {i}. {q}")
                
                # Step 1: 複数クエリで並列リサーチ
                progress(0.3, desc="Step 1: 並列リサーチ中...")
                append_log(f"\n== Step 1: 並列リサーチ ({research_mode}) ==")
                
                researcher = PerplexityResearcher(config)
                research_result = await researcher.research_multi(plan.queries, mode)
                
                append_log(f"\n✓ 並列リサーチ完了")
                append_log(f"収集した情報: {len(research_result.content)}文字")
            else:
                append_log("リサーチなしで台本生成")
            
            # Step 2: 収集した情報を元に台本生成
            progress(0.7, desc="Step 2: 台本生成中...")
            append_log(f"\n== Step 2: 台本生成 ==")
            
            if not script_generator:
                script_generator = GeminiClient(config)
            
            script = script_generator.generate(
                theme=theme.strip(),
                research_data=research_result
            )
            
            append_log(f"\n✓ 台本生成完了")
            append_log(f"  タイトル: {script.title}")
            append_log(f"  セリフ数: {len(script.dialogue)}")
            
            return script
        
        # 非同期実行
        script = asyncio.run(generate())
        
        # 台本をJSONに変換
        script_dict = {
            "title": script.title,
            "thumbnail_title": script.thumbnail_title,
            "description": script.description,
            "dialogue": [
                {
                    "speaker": line.speaker,
                    "text": line.text,
                    "section": line.section
                }
                for line in script.dialogue
            ]
        }
        script_json = json.dumps(script_dict, ensure_ascii=False, indent=2)
        
        progress(1.0, desc="完了!")
        append_log("\n" + "=" * 40)
        append_log("✓ AIプロデューサーモード完了")
        append_log("マニュアル制作タブの Step B に移動して台本を編集できます")
        
        return script_json, get_logs()
        
    except Exception as e:
        error_msg = f"台本生成中にエラーが発生しました: {str(e)}"
        append_log(f"\n❌ {error_msg}")
        import traceback
        append_log(f"\n詳細:\n{traceback.format_exc()}")
        return "", get_logs()


def synthesize_audio_from_script(
    script_json: str,
    progress=gr.Progress()
) -> tuple[str | None, str | None, str, str | None, str | None]:
    """台本JSONから音声を合成
    
    Args:
        script_json: 台本のJSON文字列
        progress: Gradio進捗バー
    
    Returns:
        (音声ファイルパス, 字幕ファイルパス, ログ出力, 音声ファイルパス(Step C用), 字幕ファイルパス(Step C用))
    """
    import asyncio
    from pathlib import Path
    from datetime import datetime
    from services.audio_synthesis import VoicevoxClient
    
    # ログをクリア
    clear_logs()
    append_log("音声合成を開始します...")
    append_log("=" * 40)
    
    # 入力検証
    if not script_json or not script_json.strip():
        error_msg = "エラー: 台本が入力されていません。"
        append_log(f"❌ {error_msg}")
        return None, None, get_logs(), None, None
    
    try:
        # JSONパース
        progress(0.1, desc="台本をパース中...")
        append_log("台本JSONをパース中...")
        
        script_dict = json.loads(script_json)
        
        # Scriptオブジェクトに変換
        from core.models.script import Script, DialogueLine
        
        dialogue_lines = []
        for line_dict in script_dict.get("dialogue", []):
            # speaker_idからspeakerへの変換（後方互換性）
            speaker = line_dict.get("speaker")
            if not speaker:
                # 古い形式のspeaker_idをspeakerに変換
                speaker_id = line_dict.get("speaker_id", "main")
                speaker = "A" if speaker_id == "main" else "B"
            dialogue_lines.append(DialogueLine(
                speaker=speaker,
                text=line_dict.get("text", ""),
                section=line_dict.get("section")
            ))
        
        script = Script(
            title=script_dict.get("title", "無題"),
            thumbnail_title=script_dict.get("thumbnail_title", script_dict.get("title", "無題")),
            description=script_dict.get("description", ""),
            dialogue=dialogue_lines
        )
        
        append_log(f"✓ 台本パース完了: {script.title}")
        append_log(f"  セリフ数: {len(script.dialogue)}")
        
    except json.JSONDecodeError as e:
        error_msg = f"JSON形式エラー: {str(e)}"
        append_log(f"❌ {error_msg}")
        append_log("ヒント: カンマやカッコの閉じ忘れがないか確認してください")
        return None, None, get_logs(), None, None
    except Exception as e:
        error_msg = f"台本の解析に失敗しました: {str(e)}"
        append_log(f"❌ {error_msg}")
        return None, None, get_logs(), None, None
    
    try:
        # 設定読み込み
        progress(0.2, desc="設定を読み込み中...")
        config = load_config(PROJECT_ROOT)
        
        # 出力ディレクトリを準備
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "output" / "manual_builds" / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        append_log(f"出力ディレクトリ: {output_dir}")
        
        # VOICEVOXクライアント作成
        progress(0.3, desc="VOICEVOXに接続中...")
        append_log("VOICEVOXエンジンに接続中...")
        voicevox = VoicevoxClient(config)
        
        # 非同期処理を実行
        async def synthesize():
            # エンジン状態確認
            if not await voicevox.check_engine_status():
                raise RuntimeError("VOICEVOXエンジンに接続できません。エンジンを起動してください。")
            append_log("✓ VOICEVOXエンジン接続OK")
            
            # 音声合成
            progress(0.4, desc="音声を合成中...")
            append_log(f"\n== 音声合成 ==")
            append_log(f"セリフ数: {len(script.dialogue)}")
            
            # 進捗コールバック
            def synthesis_progress(current: int, total: int):
                ratio = 0.4 + (current / total) * 0.5  # 0.4 -> 0.9
                progress(ratio, desc=f"音声合成中... ({current}/{total})")
                if current % 5 == 0:  # 5行ごとにログ出力
                    append_log(f"  進捗: {current}/{total}")
            
            result = await voicevox.synthesize(
                script=script,
                output_dir=output_dir,
                speed_scale_override=1.1  # デフォルト話速
            )
            
            return result
        
        # 非同期実行
        result = asyncio.run(synthesize())
        
        progress(0.95, desc="完了処理中...")
        append_log(f"\n✓ 音声合成完了")
        append_log(f"  音声ファイル: {result.audio_path.name}")
        append_log(f"  字幕ファイル: {result.subtitle_path.name}")
        append_log(f"  総時間: {result.total_duration_sec:.1f}秒")
        
        progress(1.0, desc="完了!")
        
        # Step BとStep Cの両方に同じパスを返す
        audio_path_str = str(result.audio_path)
        subtitle_path_str = str(result.subtitle_path)
        return audio_path_str, subtitle_path_str, get_logs(), audio_path_str, subtitle_path_str
        
    except Exception as e:
        error_msg = f"音声合成中にエラーが発生しました: {str(e)}"
        append_log(f"\n❌ {error_msg}")
        import traceback
        append_log(f"\n詳細:\n{traceback.format_exc()}")
        return None, None, get_logs(), None, None


def render_video_from_assets(
    audio_path: str | None,
    subtitle_path: str | None,
    background_path: str | None,
    bgm_filename: str | None,
    progress=gr.Progress()
) -> tuple[str | None, str | None, str]:
    """アセットから動画をレンダリング
    
    Args:
        audio_path: 音声ファイルパス
        subtitle_path: 字幕ファイルパス
        background_path: 背景画像パス
        bgm_filename: BGMファイル名
        progress: Gradio進捗バー
    
    Returns:
        (動画ファイルパス, 動画ファイルパス(ダウンロード用), ログ出力)
    """
    import asyncio
    from pathlib import Path
    from datetime import datetime
    from services.video_rendering import FfmpegRenderer
    from core.interfaces import SynthesisResult
    import wave
    
    # ログをクリア
    clear_logs()
    append_log("動画レンダリングを開始します...")
    append_log("=" * 40)
    
    # 入力検証
    if not audio_path:
        error_msg = "エラー: 音声ファイルが指定されていません。"
        append_log(f"❌ {error_msg}")
        return None, None, get_logs()
    
    if not subtitle_path:
        error_msg = "エラー: 字幕ファイルが指定されていません。"
        append_log(f"❌ {error_msg}")
        return None, None, get_logs()
    
    if not background_path:
        error_msg = "エラー: 背景画像が指定されていません。"
        append_log(f"❌ {error_msg}")
        return None, None, get_logs()
    
    try:
        progress(0.1, desc="設定を読み込み中...")
        
        # パスをPathオブジェクトに変換
        audio_file = Path(audio_path)
        subtitle_file = Path(subtitle_path)
        background_file = Path(background_path)
        
        # ファイル存在確認
        if not audio_file.exists():
            error_msg = f"エラー: 音声ファイルが見つかりません: {audio_path}"
            append_log(f"❌ {error_msg}")
            return None, None, get_logs()
        
        if not subtitle_file.exists():
            error_msg = f"エラー: 字幕ファイルが見つかりません: {subtitle_path}"
            append_log(f"❌ {error_msg}")
            return None, None, get_logs()
        
        if not background_file.exists():
            error_msg = f"エラー: 背景画像が見つかりません: {background_path}"
            append_log(f"❌ {error_msg}")
            return None, None, get_logs()
        
        append_log(f"✓ 入力ファイル確認完了")
        append_log(f"  音声: {audio_file.name}")
        append_log(f"  字幕: {subtitle_file.name}")
        append_log(f"  背景: {background_file.name}")
        
        # 設定読み込み
        config = load_config(PROJECT_ROOT)
        
        # BGMパスを取得
        bgm_path = None
        if bgm_filename:
            bgm_path = PROJECT_ROOT / "assets" / "bgm" / bgm_filename
            if not bgm_path.exists():
                append_log(f"⚠️ BGMファイルが見つかりません: {bgm_filename}")
                bgm_path = None
            else:
                append_log(f"  BGM: {bgm_filename}")
        
        # 出力ディレクトリを準備（音声ファイルと同じディレクトリ）
        output_dir = audio_file.parent
        video_path = output_dir / "video.mp4"
        
        append_log(f"出力先: {video_path}")
        
        # 音声ファイルの長さを取得
        try:
            with wave.open(str(audio_file), 'rb') as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                duration_sec = frames / float(rate)
        except Exception as e:
            append_log(f"⚠️ 音声ファイルの長さ取得失敗: {e}")
            duration_sec = 0.0
        
        # SynthesisResultオブジェクトを作成
        synthesis_result = SynthesisResult(
            audio_path=audio_file,
            subtitle_path=subtitle_file,
            total_duration_sec=duration_sec,
            chapters=[]
        )
        
        # FfmpegRenderer作成
        progress(0.2, desc="レンダラーを初期化中...")
        renderer = FfmpegRenderer(config)
        
        # 非同期処理を実行
        async def render():
            progress(0.3, desc="動画をレンダリング中...")
            append_log(f"\n== 動画レンダリング ==")
            
            # レンダリング実行
            result = await renderer.render(
                synthesis_result=synthesis_result,
                background_image=background_file,
                bgm_file=bgm_path,
                output_path=video_path,
                subtitle_path=subtitle_file
            )
            
            return result
        
        # 非同期実行
        result = asyncio.run(render())
        
        progress(0.95, desc="完了処理中...")
        append_log(f"\n✓ 動画レンダリング完了")
        append_log(f"  動画ファイル: {result.video_path.name}")
        append_log(f"  長さ: {result.duration_sec:.1f}秒")
        append_log(f"  サイズ: {result.file_size_mb:.1f}MB")
        
        progress(1.0, desc="完了!")
        
        video_path_str = str(result.video_path)
        return video_path_str, video_path_str, get_logs()
        
    except Exception as e:
        error_msg = f"動画レンダリング中にエラーが発生しました: {str(e)}"
        append_log(f"\n❌ {error_msg}")
        import traceback
        append_log(f"\n詳細:\n{traceback.format_exc()}")
        return None, None, get_logs()


def generate_script_from_research(
    research_text: str,
    theme: str,
    progress=gr.Progress()
) -> tuple[str, str]:
    """リサーチ結果から台本を生成
    
    Args:
        research_text: Perplexity等のリサーチ結果
        theme: テーマ/タイトル
    
    Returns:
        (台本JSON, 台本JSON) - Step AとStep Bの両方に出力
    """
    # 入力検証
    if not research_text or not research_text.strip():
        error_msg = "エラー: リサーチ結果を入力してください。"
        return error_msg, error_msg
    
    if not theme or not theme.strip():
        error_msg = "エラー: テーマ/タイトルを入力してください。"
        return error_msg, error_msg
    
    try:
        # ログをクリア
        clear_logs()
        append_log("台本生成ツール v3.3.2")
        append_log("=" * 40)
        append_log("リサーチ結果から台本を生成します...")
        
        progress(0.2, desc="設定を読み込み中...")
        
        # 設定を読み込み
        config = load_config(PROJECT_ROOT)
        script_generator = create_script_generator(config)
        
        progress(0.4, desc="リサーチデータを処理中...")
        
        # リサーチ結果を作成（簡易的な実装）
        research_result = ResearchResult(
            topic=theme.strip(),
            mode="trivia",  # マニュアル入力はトリビアモードとして扱う
            content=research_text.strip(),
            sources=["手動入力"]
        )
        
        progress(0.6, desc="台本を生成中...")
        
        # 台本を生成
        script = script_generator.generate(theme.strip(), research_result)
        
        progress(0.9, desc="結果を整形中...")
        
        # 台本をJSON形式に変換
        script_dict = {
            "title": script.title,
            "thumbnail_title": script.thumbnail_title,
            "description": script.description,
            "dialogue": [
                {
                    "speaker": line.speaker,
                    "text": line.text,
                    "section": line.section
                }
                for line in script.dialogue
            ]
        }
        
        append_log("✓ 台本生成が完了しました！")
        append_log(f"タイトル: {script.title}")
        append_log(f"セリフ数: {len(script.dialogue)}")
        if script.thumbnail_title:
            append_log(f"サムネイルタイトル: {script.thumbnail_title}")
        
        script_json = json.dumps(script_dict, ensure_ascii=False, indent=2)
        # Step AとStep Bの両方に同じ内容を返す
        return script_json, script_json
        
    except Exception as e:
        error_msg = f"台本生成中にエラーが発生しました: {str(e)}"
        append_log(f"❌ {error_msg}")
        return error_msg, error_msg


# Dashboard functions
def load_execution_logs(year_month: str) -> pd.DataFrame:
    """Load execution logs from JSONL file"""
    logs_dir = PROJECT_ROOT / "logs"
    file_path = logs_dir / f"execution_record_{year_month}.jsonl"
    
    if not file_path.exists():
        return pd.DataFrame()
    
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            data.append(json.loads(line))
    
    return pd.DataFrame(data)

def load_cost_logs(year_month: str) -> pd.DataFrame:
    """Load cost logs from JSONL file"""
    logs_dir = PROJECT_ROOT / "logs"
    file_path = logs_dir / f"cost_history_{year_month}.jsonl"
    
    if not file_path.exists():
        return pd.DataFrame()
    
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            data.append(json.loads(line))
    
    return pd.DataFrame(data)

def calculate_summary_stats(df_cost: pd.DataFrame, df_exec: pd.DataFrame) -> dict:
    """Calculate summary statistics"""
    if df_cost.empty:
        return {
            "total_executions": 0,
            "total_cost": 0.0,
            "avg_cost": 0.0,
            "success_rate": 0.0
        }
    
    total_executions = len(df_exec)
    total_cost = df_cost['total_cost_usd'].sum() if 'total_cost_usd' in df_cost.columns else 0.0
    avg_cost = total_cost / total_executions if total_executions > 0 else 0.0

    if total_executions == 0:
        success_rate = 0.0
    elif 'success' in df_exec.columns:
        success_rate = (pd.to_numeric(df_exec['success'], errors='coerce').fillna(0).sum() / total_executions) * 100
    elif 'status' in df_exec.columns:
        success_rate = ((df_exec['status'].astype(str).str.lower() == 'success').sum() / total_executions) * 100
    else:
        success_rate = 0.0
    
    return {
        "total_executions": total_executions,
        "total_cost": total_cost,
        "avg_cost": avg_cost,
        "success_rate": success_rate
    }

def create_cost_trend_chart(df_cost: pd.DataFrame) -> go.Figure:
    """Create cost trend chart"""
    if df_cost.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig
    
    df_cost['date'] = pd.to_datetime(df_cost['timestamp']).dt.date
    daily_cost = df_cost.groupby('date')['total_cost_usd'].sum().reset_index()
    
    fig = px.line(daily_cost, x='date', y='total_cost_usd', title='Daily Cost Trend')
    fig.update_layout(xaxis_title='Date', yaxis_title='Cost (USD)')
    return fig

def create_model_usage_chart(df_cost: pd.DataFrame) -> go.Figure:
    """Create model usage pie chart"""
    if df_cost.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig
    
    model_costs = {
        'Perplexity': df_cost['perplexity_cost_usd'].sum(),
        'Gemini': df_cost['gemini_cost_usd'].sum(),
        'VOICEVOX': df_cost['voicevox_cost_usd'].sum()
    }
    
    fig = px.pie(values=list(model_costs.values()), names=list(model_costs.keys()), title='Cost by Model')
    return fig

def format_execution_table(df_exec: pd.DataFrame) -> pd.DataFrame:
    """Format execution table for display"""
    if df_exec.empty:
        return pd.DataFrame(columns=['Date', 'Theme', 'Duration', 'Success', 'Cost (USD)'])
    
    if 'timestamp' in df_exec.columns:
        df_cost = load_cost_logs(str(df_exec['timestamp'].iloc[0])[:7])
    else:
        df_cost = pd.DataFrame()
    
    formatted = df_exec.copy()
    if 'timestamp' in df_exec.columns:
        formatted['Date'] = pd.to_datetime(df_exec['timestamp'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M').fillna('-')
    else:
        formatted['Date'] = '-'

    if 'execution_time_seconds' in df_exec.columns:
        duration_series = pd.to_numeric(df_exec['execution_time_seconds'], errors='coerce')
    elif 'duration_sec' in df_exec.columns:
        duration_series = pd.to_numeric(df_exec['duration_sec'], errors='coerce')
    else:
        duration_series = pd.Series([None] * len(df_exec))

    formatted['Duration'] = duration_series.apply(lambda x: f"{x:.1f}s" if pd.notna(x) else '-')

    if 'Theme' in df_exec.columns:
        formatted['Theme'] = df_exec['Theme']
    elif 'theme' in df_exec.columns:
        formatted['Theme'] = df_exec['theme']
    else:
        formatted['Theme'] = '-'

    if 'Success' in df_exec.columns:
        formatted['Success'] = df_exec['Success']
    elif 'success' in df_exec.columns:
        formatted['Success'] = df_exec['success']
    elif 'status' in df_exec.columns:
        formatted['Success'] = df_exec['status'].astype(str).str.lower() == 'success'
    else:
        formatted['Success'] = False
    
    # Merge cost data
    if not df_cost.empty and 'execution_id' in formatted.columns and 'execution_id' in df_cost.columns and 'total_cost_usd' in df_cost.columns:
        cost_map = df_cost.set_index('execution_id')['total_cost_usd'].to_dict()
        formatted['Cost (USD)'] = formatted['execution_id'].map(cost_map).fillna(0.0)
    else:
        formatted['Cost (USD)'] = 0.0
    
    return formatted[['Date', 'Theme', 'Duration', 'Success', 'Cost (USD)']]

def update_dashboard(month_selector: str):
    """Update dashboard data"""
    try:
        df_exec = load_execution_logs(month_selector)
        df_cost = load_cost_logs(month_selector)
        
        stats = calculate_summary_stats(df_cost, df_exec)
        cost_chart = create_cost_trend_chart(df_cost)
        usage_chart = create_model_usage_chart(df_cost)
        table = format_execution_table(df_exec)
        
        status = f"Data loaded for {month_selector}"
        
        return (
            stats["total_executions"],
            stats["total_cost"],
            stats["avg_cost"],
            stats["success_rate"],
            table,
            cost_chart,
            usage_chart,
            status
        )
    except Exception as e:
        return (
            0, 0.0, 0.0, 0.0,
            pd.DataFrame(columns=['Date', 'Theme', 'Duration', 'Success', 'Cost (USD)']),
            go.Figure(), go.Figure(),
            f"Error loading data: {str(e)}"
        )


def _update_config_yaml_values(upload_enabled: bool, footer_text: str) -> None:
    """Update specific config.yaml keys while keeping most existing structure intact."""
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return

    lines = config_path.read_text(encoding="utf-8").splitlines()
    updated_lines: list[str] = []
    section = ""
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped and not line.startswith(" ") and stripped.endswith(":"):
            section = stripped[:-1]

        if section == "publishing" and stripped.startswith("enable_upload:"):
            updated_lines.append(f"  enable_upload: {'true' if upload_enabled else 'false'}")
            i += 1
            continue

        if section == "publishing" and stripped.startswith("footer_text:"):
            updated_lines.append("  footer_text: |")
            for footer_line in (footer_text or "").splitlines() or [""]:
                updated_lines.append(f"    {footer_line}")

            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                if not next_stripped:
                    i += 1
                    continue
                if next_line.startswith("    "):
                    i += 1
                    continue
                break
            continue

        updated_lines.append(line)
        i += 1

    config_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def get_system_status_markdown(config) -> tuple[str, str, str]:
    """Build system status texts for Settings tab."""
    perplexity_key = os.getenv("PERPLEXITY_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    perplexity_status = "🟢 Perplexity: Configured" if perplexity_key else "🔴 Perplexity: Missing API Key"
    gemini_status = "🟢 Gemini: Configured" if gemini_key else "🔴 Gemini: Missing API Key"

    voicevox_url = getattr(config.env, "voicevox_base_url", "http://localhost:50021")
    parsed = urlparse(voicevox_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 50021
    voicevox_ok = False
    try:
        with socket.create_connection((host, port), timeout=0.8):
            voicevox_ok = True
    except OSError:
        voicevox_ok = False

    if voicevox_ok:
        voicevox_status = f"🟢 VOICEVOX: Connected ({host}:{port})"
    else:
        voicevox_status = f"🔴 VOICEVOX: Not reachable ({host}:{port})"

    return perplexity_status, gemini_status, voicevox_status


def save_settings_from_ui(
    research_mode: str,
    background_image: str,
    bgm_file: str,
    bgm_volume: float,
    fade_time: float,
    speed_scale: float,
    enable_spectrum: bool,
    upload_enabled: bool,
    footer_text: str,
):
    """Persist settings only when user explicitly clicks Save Settings."""
    _settings_manager.update_from_ui(
        research_mode=research_mode,
        background_image=background_image,
        bgm_file=bgm_file,
        bgm_volume=bgm_volume,
        fade_time=fade_time,
        speed_scale=speed_scale,
        enable_spectrum=enable_spectrum,
    )

    _update_config_yaml_values(
        upload_enabled=upload_enabled,
        footer_text=footer_text,
    )

    return f"✅ Settings saved ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"


def create_dashboard_tab() -> dict[str, gr.components.Component]:
    """Create Dashboard tab UI components and return references for event binding."""
    gr.Markdown("## 📊 Cost & Execution Analytics")

    logs_dir = PROJECT_ROOT / "logs"
    available_months: list[str] = []
    if logs_dir.exists():
        for file in logs_dir.glob("execution_record_*.jsonl"):
            month = file.stem.split("_")[-1]
            if month not in available_months:
                available_months.append(month)
    available_months.sort(reverse=True)

    if not available_months:
        available_months = [datetime.now().strftime("%Y-%m")]

    with gr.Row():
        with gr.Column():
            total_executions = gr.Number(label="Total Executions", interactive=False, value=0)
            total_cost_usd = gr.Number(label="Total Cost (USD)", interactive=False, value=0.0)
        with gr.Column():
            avg_cost = gr.Number(label="Avg Cost/Video", interactive=False, value=0.0)
            success_rate = gr.Number(label="Success Rate (%)", interactive=False, value=0.0)

    with gr.Row():
        month_selector = gr.Dropdown(
            label="Select Month",
            choices=available_months,
            value=available_months[0],
        )
        refresh_btn = gr.Button("🔄 Refresh Data", size="sm")

    with gr.Row():
        with gr.Column(scale=2):
            execution_table = gr.Dataframe(
                label="Execution History",
                headers=["Date", "Theme", "Duration", "Success", "Cost (USD)"],
                datatype=["str", "str", "str", "bool", "number"],
                interactive=False,
            )
        with gr.Column(scale=1):
            cost_chart = gr.Plot(label="Cost Trend")
            usage_chart = gr.Plot(label="Model Usage")

    dashboard_status = gr.Markdown("*Run your first generation to see data.*")

    return {
        "month_selector": month_selector,
        "refresh_btn": refresh_btn,
        "total_executions": total_executions,
        "total_cost_usd": total_cost_usd,
        "avg_cost": avg_cost,
        "success_rate": success_rate,
        "execution_table": execution_table,
        "cost_chart": cost_chart,
        "usage_chart": usage_chart,
        "dashboard_status": dashboard_status,
    }


def create_settings_tab(
    config,
    default_upload_enabled: bool,
    default_footer_text: str,
) -> dict[str, gr.components.Component]:
    """Create Settings tab with explicit save flow and hidden developer options."""
    gr.Markdown("## ⚙️ Settings")

    with gr.Row():
        with gr.Column():
            gr.Markdown("### 📡 System Status")
            perplexity_status = gr.Markdown("🔴 Perplexity: Checking...")
            gemini_status = gr.Markdown("🔴 Gemini: Checking...")
            voicevox_status = gr.Markdown("🔴 VOICEVOX: Checking...")
            refresh_status_btn = gr.Button("🔄 Refresh Status", size="sm")

        with gr.Column():
            gr.Markdown("### 🚀 Publishing")
            upload_to_youtube_checkbox = gr.Checkbox(
                label="YouTubeに自動アップロードする",
                value=default_upload_enabled,
                info="チェック時は動画生成後にYouTubeへ自動アップロードを試行します",
            )
            footer_text_input = gr.Textbox(
                label="概要欄フッター（固定文）",
                value=default_footer_text,
                lines=6,
                info="著作権表示・免責事項などを設定できます（Save Settingsで反映）",
            )

    with gr.Accordion("Developer Options", open=False):
        mock_generate_btn = gr.Button(
            "🧪 モックで動画を作成",
            variant="secondary",
            size="lg",
        )
        gr.Markdown("- このボタンは常にMockモードで実行されます（テーマ未入力でも実行可）")
        gr.Markdown("- Current Config Source: `config.yaml`\n- Runtime UI state: saved only by **Save Settings**")

    save_settings_btn = gr.Button("💾 Save Settings", variant="primary")
    settings_status = gr.Markdown("*Settings not saved yet.*")

    return {
        "perplexity_status": perplexity_status,
        "gemini_status": gemini_status,
        "voicevox_status": voicevox_status,
        "refresh_status_btn": refresh_status_btn,
        "upload_to_youtube_checkbox": upload_to_youtube_checkbox,
        "footer_text_input": footer_text_input,
        "mock_generate_btn": mock_generate_btn,
        "save_settings_btn": save_settings_btn,
        "settings_status": settings_status,
        "config": config,
    }


def regenerate_thumbnail_from_state(
    state: Optional[ThumbnailRegenerationState]
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[ThumbnailRegenerationState], str]:
    """Stateからサムネイルを再作成
    
    Args:
        state: サムネイル再作成状態
        
    Returns:
        tuple: (thumbnail_path, video_title, thumbnail_title, updated_state, log_message)
    """
    # 1. Stateのバリデーション
    if state is None:
        error_log = "⚠️ 動画生成が完了していません。先にメインの動画生成を実行してください。"
        return None, None, None, None, error_log
    
    # 必須プロパティのチェック
    required_fields = ['theme', 'output_dir', 'background_path', 'base_title']
    missing_fields = [field for field in required_fields if not getattr(state, field, None)]
    if missing_fields:
        error_log = f"⚠️ 必要な情報が不足しています: {', '.join(missing_fields)}。動画生成からやり直してください。"
        return None, None, None, None, error_log
    
    try:
        # ログ開始
        log_messages = ["🔄 サムネイル再作成を開始します..."]
        log_messages.append(f"テーマ: {state.theme}")
        log_messages.append(f"出力先: {state.output_dir}")
        log_messages.append(f"背景画像: {state.background_path}")
        
        # 台本要約を生成（既存の台本から）
        script_summary = ""
        if state.script_summary:
            script_summary = state.script_summary[:200] + "..." if len(state.script_summary) > 200 else state.script_summary
        log_messages.append(f"台本要約: {script_summary[:50]}...")
        
        # 背景画像パスを解決
        from core.models.config import load_config
        config = load_config()
        if state.background_path.startswith("assets/"):
            background_path = PROJECT_ROOT / state.background_path
        else:
            background_path = Path(state.background_path)
        
        # 背景画像の存在確認
        if not background_path.exists():
            error_log = f"❌ 背景画像が見つかりません: {background_path}"
            log_messages.append(error_log)
            return None, None, None, None, "\n".join(log_messages)
        
        log_messages.append(f"✓ 背景画像確認: {background_path}")
        
        # 出力ディレクトリの存在確認
        output_dir = Path(state.output_dir)
        if not output_dir.exists():
            error_log = f"❌ 出力ディレクトリが見つかりません: {output_dir}"
            log_messages.append(error_log)
            return None, None, None, None, "\n".join(log_messages)
        
        log_messages.append(f"✓ 出力ディレクトリ確認: {output_dir}")
        
        # ThumbnailGeneratorで再作成
        log_messages.append("🖼️ サムネイル画像を生成中...")
        thumbnail_generator = ThumbnailGenerator()
        thumbnail_path, video_title, thumbnail_title = thumbnail_generator.regenerate_with_new_title(
            theme=state.theme,
            script_summary=script_summary,
            output_dir=state.output_dir,
            background_path=str(background_path),
            base_title=state.base_title,
            generation_count=state.generation_count
        )
        
        # Stateを更新
        updated_state = ThumbnailRegenerationState(
            theme=state.theme,
            script_summary=state.script_summary,
            output_dir=state.output_dir,
            background_path=state.background_path,
            base_title=state.base_title,
            generation_count=state.generation_count + 1
        )
        
        # 成功ログ
        log_messages.append("✅ サムネイル再作成が完了しました！")
        log_messages.append(f"生成画像: {thumbnail_path}")
        log_messages.append(f"動画タイトル: {video_title}")
        log_messages.append(f"サムネイル文字: {thumbnail_title}")
        
        return thumbnail_path, video_title, thumbnail_title, updated_state, "\n".join(log_messages)
        
    except Exception as e:
        # エラーハンドリングと詳細ログ
        import traceback
        error_detail = traceback.format_exc()
        error_log = f"❌ サムネイル再作成中にエラーが発生しました:\n{str(e)}\n\n詳細:\n{error_detail}"
        return None, None, None, state, error_log


def create_generator_tab(saved_settings, assets: dict) -> dict[str, object]:
    """Create Generator tab UI and return component references."""
    with gr.Accordion("🚀 全自動モード", open=True):
        with gr.Row():
            with gr.Column(scale=1):
                with gr.Group(elem_classes="group-container"):
                    gr.Markdown("### 📋 企画設定")

                    with gr.Row():
                        theme_input = gr.Textbox(
                            label="テーマ",
                            placeholder="例: AIの未来について / 最近のゲーム事情 / 宇宙開発の最新動向",
                            lines=2,
                            info="動画で話すテーマを入力してください（必須）",
                            scale=2,
                        )
                        research_mode_dropdown = gr.Dropdown(
                            label="リサーチモード",
                            choices=list(RESEARCH_MODE_MAP.keys()),
                            value=saved_settings.research_mode,
                            info="Perplexityによるリサーチの方向性を選択",
                            scale=1,
                        )
                    
                    with gr.Row():
                        llm_provider_dropdown = gr.Dropdown(
                            label="🤖 LLMプロバイダー",
                            choices=["gemini", "openai", "anthropic"],
                            value="gemini",
                            info="台本生成に使用するAIモデルを選択",
                            scale=1,
                        )

                    avoid_topics_input = gr.Textbox(
                        label="避けてほしい話題 (オプション)",
                        placeholder="例: 食事療法 運動不足 (スペースやカンマで区切って複数入力可)",
                        lines=1,
                        info="台本に含めたくないトピックを指定できます",
                    )

                    # 第2部モード設定
                    gr.Markdown("### 📖 第2部モード (2-Story Mode)")
                    with gr.Row():
                        second_mode_dropdown = gr.Dropdown(
                            label="第2部のモード (オプション)",
                            choices=["なし"] + list(RESEARCH_MODE_MAP.keys()),
                            value="なし",
                            info="第2部で異なるリサーチモードを使用します",
                            scale=1,
                        )
                        jingle_dropdown = gr.Dropdown(
                            label="場面転換ジングル",
                            choices=["なし", "デフォルト", "カスタムファイル"],
                            value="なし",
                            info="第1部と第2部の間に挿入するジングル",
                            scale=1,
                        )
                    
                    jingle_path_input = gr.Textbox(
                        label="ジングルファイルパス",
                        placeholder="assets/jingles/custom.mp3",
                        visible=False,
                        info="カスタムジングルファイルのパスを指定",
                    )

                with gr.Group(elem_classes="group-container"):
                    gr.Markdown("### 🎨 クリエイティブ設定")
                    gr.Markdown("#### 📷 背景画像")

                    with gr.Row(equal_height=True):
                        with gr.Column(scale=1):
                            bg_preview = gr.Image(label="プレビュー", height=300, interactive=False)
                            selected_bg_filename = gr.Textbox(
                                value=saved_settings.background_image
                                if saved_settings.background_image
                                else (assets.get("backgrounds", ["default.png"])[0] if assets.get("backgrounds") else ""),
                                visible=False,
                            )

                        with gr.Column(scale=1):
                            custom_bg_upload = gr.File(
                                label="カスタム画像をアップロード",
                                file_types=["image"],
                                type="filepath",
                            )
                            gr.Markdown(
                                """
                                **アップロード情報:**
                                - PNG, JPG, WEBP対応
                                - 推奨: 1920x1080以上
                                """
                            )

                    bg_gallery = gr.Gallery(
                        label="背景画像ギャラリー",
                        value=get_background_gallery_images(),
                        columns=4,
                        height=200,
                        object_fit="cover",
                        elem_classes="gallery-container",
                    )

                    gr.Markdown("#### 🎵 BGM")
                    with gr.Row():
                        bgm_dropdown = gr.Dropdown(
                            label="BGM選択",
                            choices=assets.get("bgm", ["default.mp3"]),
                            value=saved_settings.bgm_file
                            if saved_settings.bgm_file in assets.get("bgm", [])
                            else (assets.get("bgm", ["default.mp3"])[0] if assets.get("bgm") else None),
                            scale=2,
                        )
                        bgm_preview = gr.Audio(label="プレビュー", interactive=False, scale=1)

                    refresh_assets_btn = gr.Button("🔄 素材リストを更新", size="sm")
                    gr.Markdown("#### ⚙️ 動画設定")

                    with gr.Row():
                        bgm_volume_slider = gr.Slider(
                            label="BGM音量",
                            minimum=0.0,
                            maximum=0.5,
                            value=saved_settings.bgm_volume,
                            step=0.01,
                            info="BGMの音量（0.0〜0.5）",
                        )
                        fade_time_slider = gr.Slider(
                            label="フェード時間",
                            minimum=1.0,
                            maximum=10.0,
                            value=saved_settings.fade_time,
                            step=0.5,
                            info="BGMのフェードイン/アウト時間（秒）",
                        )

                    with gr.Row():
                        speed_slider = gr.Slider(
                            label="話速 (Speed)",
                            minimum=0.8,
                            maximum=1.5,
                            value=saved_settings.speed_scale,
                            step=0.05,
                            info="音声の再生速度（0.8～1.5）",
                        )
                        spectrum_checkbox = gr.Checkbox(
                            label="音声スペクトラムを表示",
                            value=saved_settings.enable_spectrum,
                            info="画面下部に音声の波形を表示",
                        )

                with gr.Group(elem_classes="group-container"):
                    gr.Markdown("### � APIヘルスチェック")
                    
                    with gr.Row():
                        gemini_status = gr.Markdown("Gemini: 🟡待機中")
                        perplexity_status = gr.Markdown("Perplexity: 🟡待機中")
                    
                    check_api_btn = gr.Button("🔍 Check API Status", size="sm", variant="secondary")
                    
                    gr.Markdown(
                        """
                        **使い方:**
                        - 生成前にAPI接続状態を確認できます
                        - 🟢OK: 正常接続 / 🔴Error: 接続不可
                        - エラー時はAPIキーやネットワークを確認してください
                        """
                    )

                with gr.Group(elem_classes="group-container"):
                    gr.Markdown("### � 生成アクション")
                    with gr.Row():
                        generate_btn = gr.Button(
                            "🚀 動画を生成する",
                            variant="primary",
                            size="lg",
                            scale=2,
                            elem_classes="primary-btn",
                        )
                        script_only_btn = gr.Button(
                            "📝 台本のみ作成",
                            variant="secondary",
                            size="lg",
                            scale=1,
                        )

                    gr.Markdown(
                        """
                        **⚠️ 注意事項:**
                        - **VOICEVOX** エンジンが起動している必要があります
                        - **Perplexity API Key** と **Gemini API Key** が `.env` に設定されている必要があります
                        - 生成には数分かかる場合があります
                        """
                    )

            with gr.Column(scale=1):
                gr.Markdown("## 📺 結果パネル")
                video_output = gr.Video(label="生成された動画", height=360)
                youtube_url_output = gr.Markdown(value="")
                log_output = gr.Textbox(label="処理ログ", lines=12, max_lines=18, interactive=False)
                gr.Markdown("### 📊 API使用量・コスト")
                cost_output = gr.Markdown(value="*生成完了後に表示されます*")
                gr.Markdown("### 📝 YouTubeメタデータ")
                title_output = gr.Textbox(label="タイトル (コピー用)", placeholder="生成完了後に表示されます", interactive=True)
                description_output = gr.Textbox(
                    label="概要欄・チャプター (一括コピー用)",
                    placeholder="生成完了後に表示されます",
                    lines=15,
                    interactive=True,
                )
                
                # サムネイル再作成機能
                gr.Markdown("---")
                gr.Markdown("### 🔄 サムネイルのみ再作成")
                
                with gr.Accordion("🔄 サムネイル＆タイトル再作成", open=False):
                    gr.Markdown(
                        """
                        **動画生成後にサムネイルのみを再作成** - A/Bテスト対応
                        
                        🔹 **押すたびに新しいタイトル**: Geminiが創造的な切り口を提案
                        🔹 **高速生成**: 軽量プロンプトで素早く処理
                        🔹 **バージョン管理**: タイムスタンプ付きで複数保存
                        """
                    )
                    
                    regenerate_thumbnail_btn = gr.Button("🔄 サムネイルを再作成", variant="secondary", size="lg")
                    
                    with gr.Row():
                        with gr.Column():
                            thumbnail_preview = gr.Image(label="新しいサムネイル", interactive=False)
                        with gr.Column():
                            regenerated_title = gr.Textbox(label="生成されたタイトル", interactive=False, lines=2)
                            regenerated_thumbnail_title = gr.Textbox(label="サムネイル文字", interactive=False)
                            regenerate_status = gr.Textbox(label="処理ログ", lines=5, interactive=False)

    step_components = create_step_mode_ui(assets)

    return {
        "theme_input": theme_input,
        "research_mode_dropdown": research_mode_dropdown,
        "llm_provider_dropdown": llm_provider_dropdown,
        "second_mode_dropdown": second_mode_dropdown,
        "jingle_dropdown": jingle_dropdown,
        "jingle_path_input": jingle_path_input,
        "avoid_topics_input": avoid_topics_input,
        "bg_preview": bg_preview,
        "selected_bg_filename": selected_bg_filename,
        "custom_bg_upload": custom_bg_upload,
        "bg_gallery": bg_gallery,
        "bgm_dropdown": bgm_dropdown,
        "bgm_preview": bgm_preview,
        "refresh_assets_btn": refresh_assets_btn,
        "bgm_volume_slider": bgm_volume_slider,
        "fade_time_slider": fade_time_slider,
        "speed_slider": speed_slider,
        "spectrum_checkbox": spectrum_checkbox,
        "gemini_status": gemini_status,
        "perplexity_status": perplexity_status,
        "check_api_btn": check_api_btn,
        "generate_btn": generate_btn,
        "script_only_btn": script_only_btn,
        "video_output": video_output,
        "youtube_url_output": youtube_url_output,
        "log_output": log_output,
        "cost_output": cost_output,
        "title_output": title_output,
        "description_output": description_output,
        "regenerate_thumbnail_btn": regenerate_thumbnail_btn,
        "thumbnail_preview": thumbnail_preview,
        "regenerated_title": regenerated_title,
        "regenerated_thumbnail_title": regenerated_thumbnail_title,
        "regenerate_status": regenerate_status,
        "step_components": step_components,
    }


def create_manual_tab(assets: dict) -> dict[str, object]:
    """Create Manual tab UI and return component references."""
    with gr.Accordion("🛠 こだわりステップモード", open=False):
        gr.Markdown(
            """
            **高度な制作モード** - 各ステップを個別に実行・調整できます

            🔹 **Step A**: リサーチ → 台本生成（個別調整可能）
            🔹 **Step B**: 台本 → 音声合成（個別調整可能）
            🔹 **Step C**: 音声・字幕 → 動画レンダリング（個別調整可能）
            """
        )

        step_mode = gr.Radio(
            choices=["通常モード（一括）", "こだわりステップモード"],
            value="通常モード（一括）",
            label="制作モード",
            info="こだわりステップモードでは各工程を個別に実行・調整できます",
        )

    gr.Markdown("### 📝 Step A: リサーチ結果から台本生成")
    research_input = gr.Textbox(
        label="Perplexity等のリサーチ結果を貼り付け",
        placeholder="ここにリサーチ結果のテキストを貼り付けてください...",
        lines=10,
        info="Perplexityや他のソースで得たリサーチ結果を貼り付け",
    )
    theme_input_manual = gr.Textbox(
        label="テーマ/タイトル",
        placeholder="例: AIの倫理的課題について",
        info="台本のテーマまたはタイトルを入力してください",
    )
    generate_script_btn = gr.Button("📝 この内容で台本を作成", variant="primary", size="lg")
    script_output = gr.Code(label="生成された台本", language="json", lines=20, interactive=True)

    gr.Markdown("---")
    gr.Markdown("### 🎤 Step B: 音声合成 (Audio Synthesis)")
    script_editor = gr.Code(
        label="台本JSON (編集可能) - Step Aで生成された台本を編集できます",
        language="json",
        lines=15,
        interactive=True,
    )
    synthesize_btn = gr.Button("🎤 この台本で音声を合成する", variant="primary", size="lg")

    with gr.Row():
        with gr.Column():
            audio_output = gr.Audio(label="生成された音声", interactive=False)
            subtitle_output = gr.File(label="字幕ファイル (.ass)", interactive=False)
        with gr.Column():
            synthesis_log = gr.Textbox(label="処理ログ", lines=10, interactive=False)

    gr.Markdown("---")
    gr.Markdown("### 🎬 Step C: 動画書き出し (Rendering)")

    with gr.Row():
        with gr.Column():
            audio_input = gr.Audio(label="音声ファイル", sources=["upload"], type="filepath", interactive=True)
            subtitle_input = gr.File(
                label="字幕ファイル (.ass)",
                file_types=[".ass"],
                type="filepath",
                interactive=True,
            )
        with gr.Column():
            background_input = gr.Image(
                label="背景/サムネイル画像 (1920x1080推奨)",
                sources=["upload"],
                type="filepath",
                interactive=True,
            )
            bgm_dropdown_manual = gr.Dropdown(
                label="BGM",
                choices=assets.get("bgm", ["default.mp3"]),
                value=assets.get("bgm", ["default.mp3"])[0] if assets.get("bgm") else None,
                info="assets/bgm/ 内の音声",
            )

    render_btn = gr.Button("🎬 動画を生成する (Render Video)", variant="primary", size="lg")

    with gr.Row():
        with gr.Column():
            video_output_manual = gr.Video(label="完成動画", interactive=False)
            video_file_output = gr.File(label="動画ファイルダウンロード", interactive=False)
        with gr.Column():
            render_log = gr.Textbox(label="処理ログ", lines=10, interactive=False)

    gr.Markdown(
        """
        ### 📖 使い方

        **Step A: 台本生成**
        1. Perplexity等でリサーチした結果を上のテキストボックスに貼り付け
        2. テーマ/タイトルを入力
        3. 「この内容で台本を作成」ボタンをクリック

        **Step B: 音声合成**
        1. 生成された台本が自動的にエディタに反映されます
        2. 必要に応じて台本を編集
        3. 「この台本で音声を合成する」ボタンをクリック
        4. 生成された音声と字幕がStep Cに自動反映されます

        **Step C: 動画レンダリング**
        1. Step Bの音声と字幕が自動的にセットされます
        2. 背景画像をアップロード
        3. BGMを選択
        4. 「動画を生成する」ボタンをクリック
        5. 完成した動画をダウンロード
        """
    )

    return {
        "step_mode": step_mode,
        "research_input": research_input,
        "theme_input_manual": theme_input_manual,
        "generate_script_btn": generate_script_btn,
        "script_output": script_output,
        "script_editor": script_editor,
        "synthesize_btn": synthesize_btn,
        "audio_output": audio_output,
        "subtitle_output": subtitle_output,
        "synthesis_log": synthesis_log,
        "audio_input": audio_input,
        "subtitle_input": subtitle_input,
        "background_input": background_input,
        "bgm_dropdown_manual": bgm_dropdown_manual,
        "render_btn": render_btn,
        "video_output_manual": video_output_manual,
        "video_file_output": video_file_output,
        "render_log": render_log,
    }


def create_ui() -> gr.Blocks:
    """Gradio UIを作成"""
    
    # 前回の設定を読み込む
    saved_settings = _settings_manager.load()
    config = load_config(PROJECT_ROOT)
    publishing_cfg = getattr(config.yaml, "publishing", None)
    default_enable_upload = bool(
        publishing_cfg and getattr(publishing_cfg, "enable_upload", False)
    )
    default_footer_text = (
        getattr(publishing_cfg, "footer_text", "") if publishing_cfg else ""
    )
    # アセット一覧を取得
    assets = get_asset_choices()
    
    with gr.Blocks(title="自動ラジオ動画生成システム v3.3.2") as app:
        
        # ヘッダー
        gr.Markdown(
            """
            # 🎙️ 自動ラジオ動画生成システム v3.3.2
            
            **Perplexity** でテーマをリサーチし、**Gemini** が台本を作成。
            **VOICEVOX** で音声合成、**FFmpeg** で動画を生成します。
            """
        )
        
        generator_components: dict[str, object] = {}
        manual_components: dict[str, object] = {}
        dashboard_components: dict[str, gr.components.Component] = {}
        settings_components: dict[str, gr.components.Component] = {}

        # タブ切り替え
        with gr.Tabs():
            # サムネイル再作成用State
            thumbnail_state = gr.State(value=None)
            
            with gr.TabItem("🎬 Generator", id="generator"):
                generator_components = create_generator_tab(saved_settings=saved_settings, assets=assets)

            # Tab 2: Dashboard
            with gr.TabItem("📊 Dashboard", id="dashboard"):
                dashboard_components = create_dashboard_tab()

            # Tab 3: Settings
            with gr.TabItem("⚙️ Settings", id="settings"):
                settings_components = create_settings_tab(
                    config=config,
                    default_upload_enabled=default_enable_upload,
                    default_footer_text=default_footer_text,
                )
            
            with gr.TabItem("🛠️ Manual", id="manual"):
                manual_components = create_manual_tab(assets=assets)

        step_components = generator_components["step_components"]
        
        # フッター
        gr.Markdown(
            """
            ---
            *自動ラジオ動画生成システム v3.3.2 | Powered by Perplexity, Gemini, VOICEVOX, FFmpeg*
            """
        )
        
        # ========== イベントハンドラ ==========
        
        # 素材リスト更新
        def refresh_assets():
            new_assets = get_asset_choices()
            bg_choices = new_assets.get("backgrounds", [])
            bgm_choices = new_assets.get("bgm", [])
            return (
                gr.update(choices=bg_choices, value=bg_choices[0] if bg_choices else None),
                gr.update(choices=bgm_choices, value=bgm_choices[0] if bgm_choices else None)
            )
        
        generator_components["refresh_assets_btn"].click(
            fn=lambda: (get_background_gallery_images(), gr.update(choices=get_asset_choices().get("bgm", []))),
            inputs=[],
            outputs=[generator_components["bg_gallery"], generator_components["bgm_dropdown"]]
        )
        
        # 背景画像ギャラリーから選択
        generator_components["bg_gallery"].select(
            fn=handle_gallery_select,
            inputs=[],
            outputs=[generator_components["bg_preview"], generator_components["selected_bg_filename"]]
        )
        
        # カスタム背景画像をアップロード
        generator_components["custom_bg_upload"].change(
            fn=handle_custom_upload,
            inputs=[generator_components["custom_bg_upload"]],
            outputs=[generator_components["bg_preview"], generator_components["selected_bg_filename"]]
        )
        
        # BGMプレビューの更新
        def update_bgm_preview(filename):
            if filename:
                bgm_path = PROJECT_ROOT / "assets" / "bgm" / filename
                return str(bgm_path) if bgm_path.exists() else None
            return None
        
        generator_components["bgm_dropdown"].change(
            fn=update_bgm_preview,
            inputs=[generator_components["bgm_dropdown"]],
            outputs=[generator_components["bgm_preview"]]
        )
        
        # 初期表示: 保存された設定から背景画像とBGMをプレビューに表示
        def load_initial_previews(bg_filename, bgm_filename):
            """起動時に保存された設定から背景画像とBGMをプレビューに表示"""
            bg_path = None
            if bg_filename:
                bg_path = get_background_image_path(bg_filename)
            
            bgm_path = None
            if bgm_filename:
                bgm_file_path = PROJECT_ROOT / "assets" / "bgm" / bgm_filename
                if bgm_file_path.exists():
                    bgm_path = str(bgm_file_path)
            
            return bg_path, bgm_path
        
        app.load(
            fn=load_initial_previews,
            inputs=[generator_components["selected_bg_filename"], generator_components["bgm_dropdown"]],
            outputs=[generator_components["bg_preview"], generator_components["bgm_preview"]]
        )

        dashboard_outputs = [
            dashboard_components["total_executions"],
            dashboard_components["total_cost_usd"],
            dashboard_components["avg_cost"],
            dashboard_components["success_rate"],
            dashboard_components["execution_table"],
            dashboard_components["cost_chart"],
            dashboard_components["usage_chart"],
            dashboard_components["dashboard_status"],
        ]

        dashboard_components["month_selector"].change(
            fn=update_dashboard,
            inputs=[dashboard_components["month_selector"]],
            outputs=dashboard_outputs,
        )

        dashboard_components["refresh_btn"].click(
            fn=update_dashboard,
            inputs=[dashboard_components["month_selector"]],
            outputs=dashboard_outputs,
        )

        app.load(
            fn=update_dashboard,
            inputs=[dashboard_components["month_selector"]],
            outputs=dashboard_outputs,
        )

        settings_components["refresh_status_btn"].click(
            fn=lambda: get_system_status_markdown(config),
            inputs=[],
            outputs=[
                settings_components["perplexity_status"],
                settings_components["gemini_status"],
                settings_components["voicevox_status"],
            ],
        )

        app.load(
            fn=lambda: get_system_status_markdown(config),
            inputs=[],
            outputs=[
                settings_components["perplexity_status"],
                settings_components["gemini_status"],
                settings_components["voicevox_status"],
            ],
        )

        settings_components["save_settings_btn"].click(
            fn=save_settings_from_ui,
            inputs=[
                generator_components["research_mode_dropdown"],
                generator_components["selected_bg_filename"],
                generator_components["bgm_dropdown"],
                generator_components["bgm_volume_slider"],
                generator_components["fade_time_slider"],
                generator_components["speed_slider"],
                generator_components["spectrum_checkbox"],
                settings_components["upload_to_youtube_checkbox"],
                settings_components["footer_text_input"],
            ],
            outputs=[settings_components["settings_status"]],
        )
        
        # ジングル選択時のイベントハンドラ
        generator_components["jingle_dropdown"].change(
            fn=toggle_jingle_path_visibility,
            inputs=[generator_components["jingle_dropdown"]],
            outputs=[generator_components["jingle_path_input"]],
        )
        
        # 動画生成
        generator_components["generate_btn"].click(
            fn=generate_video,
            inputs=[
                generator_components["theme_input"],
                generator_components["research_mode_dropdown"],
                generator_components["llm_provider_dropdown"],
                generator_components["selected_bg_filename"],
                generator_components["bgm_dropdown"],
                generator_components["bgm_volume_slider"],
                generator_components["fade_time_slider"],
                generator_components["speed_slider"],
                generator_components["spectrum_checkbox"],
                generator_components["avoid_topics_input"],
                settings_components["upload_to_youtube_checkbox"],
                settings_components["footer_text_input"],
                gr.Checkbox(value=False, visible=False),  # use_mock placeholder
                generator_components["second_mode_dropdown"],
                generator_components["jingle_dropdown"],
                generator_components["jingle_path_input"],
            ],
            outputs=[
                generator_components["video_output"],
                generator_components["log_output"],
                generator_components["cost_output"],
                generator_components["title_output"],
                generator_components["description_output"],
                generator_components["youtube_url_output"],
                thumbnail_state,  # Stateを更新
            ],
            show_progress="full"
        )
        
        # サムネイル再作成
        generator_components["regenerate_thumbnail_btn"].click(
            fn=regenerate_thumbnail_from_state,
            inputs=[thumbnail_state],
            outputs=[
                generator_components["thumbnail_preview"],
                generator_components["regenerated_title"],
                generator_components["regenerated_thumbnail_title"],
                thumbnail_state,  # Stateを更新
                generator_components["regenerate_status"],  # ログ出力を追加
            ]
        )

        settings_components["mock_generate_btn"].click(
            fn=generate_video_mock,
            inputs=[
                generator_components["theme_input"],
                generator_components["research_mode_dropdown"],
                generator_components["llm_provider_dropdown"],
                generator_components["selected_bg_filename"],
                generator_components["bgm_dropdown"],
                generator_components["bgm_volume_slider"],
                generator_components["fade_time_slider"],
                generator_components["speed_slider"],
                generator_components["spectrum_checkbox"],
                generator_components["avoid_topics_input"],
                settings_components["upload_to_youtube_checkbox"],
                settings_components["footer_text_input"],
                generator_components["second_mode_dropdown"],
                generator_components["jingle_dropdown"],
                generator_components["jingle_path_input"],
            ],
            outputs=[
                generator_components["video_output"],
                generator_components["log_output"],
                generator_components["cost_output"],
                generator_components["title_output"],
                generator_components["description_output"],
                generator_components["youtube_url_output"],
                thumbnail_state,  # Stateを更新
            ],
            show_progress="full",
        )
        
        # APIヘルスチェック
        def update_api_status():
            """Update API status display"""
            try:
                gemini_status, perplexity_status = run_api_health_check()
                return (
                    f"Gemini: {gemini_status}",
                    f"Perplexity: {perplexity_status}"
                )
            except Exception as e:
                return (
                    f"Gemini: 🔴Error (チェック失敗)",
                    f"Perplexity: 🔴Error (チェック失敗)"
                )
        
        def check_generate_button_state(gemini_status_text, perplexity_status_text):
            """Check if both APIs are OK and enable/disable generate button accordingly"""
            gemini_ok = "🟢OK" in gemini_status_text
            perplexity_ok = "🟢OK" in perplexity_status_text
            
            if gemini_ok and perplexity_ok:
                return gr.update(interactive=True, variant="primary")
            else:
                return gr.update(interactive=False, variant="secondary")
        
        generator_components["check_api_btn"].click(
            fn=update_api_status,
            inputs=[],
            outputs=[
                generator_components["gemini_status"],
                generator_components["perplexity_status"]
            ]
        )
        
        # Auto-update generate button state when status changes
        generator_components["gemini_status"].change(
            fn=check_generate_button_state,
            inputs=[
                generator_components["gemini_status"],
                generator_components["perplexity_status"]
            ],
            outputs=[generator_components["generate_btn"]]
        )
        
        generator_components["perplexity_status"].change(
            fn=check_generate_button_state,
            inputs=[
                generator_components["gemini_status"],
                generator_components["perplexity_status"]
            ],
            outputs=[generator_components["generate_btn"]]
        )
        
        # 台本のみ作成（AIプロデューサーモード）
        generator_components["script_only_btn"].click(
            fn=generate_script_only,
            inputs=[generator_components["theme_input"], generator_components["research_mode_dropdown"]],
            outputs=[manual_components["script_editor"], generator_components["log_output"]],
            show_progress="full"
        )
        
        # 台本生成 (Step Aの出力をStep Bのエディタにも反映)
        manual_components["generate_script_btn"].click(
            fn=generate_script_from_research,
            inputs=[manual_components["research_input"], manual_components["theme_input_manual"]],
            outputs=[manual_components["script_output"], manual_components["script_editor"]],
            show_progress="full"
        )
        
        # 音声合成 (Step B) - Step Cの入力にも反映
        manual_components["synthesize_btn"].click(
            fn=synthesize_audio_from_script,
            inputs=[manual_components["script_editor"]],
            outputs=[
                manual_components["audio_output"],
                manual_components["subtitle_output"],
                manual_components["synthesis_log"],
                manual_components["audio_input"],
                manual_components["subtitle_input"],
            ],
            show_progress="full"
        )
        
        # 動画レンダリング (Step C)
        manual_components["render_btn"].click(
            fn=render_video_from_assets,
            inputs=[
                manual_components["audio_input"],
                manual_components["subtitle_input"],
                manual_components["background_input"],
                manual_components["bgm_dropdown_manual"],
            ],
            outputs=[
                manual_components["video_output_manual"],
                manual_components["video_file_output"],
                manual_components["render_log"],
            ],
            show_progress="full"
        )
        
        # ========== こだわりステップモードのイベントハンドラ ==========
        
        # Step 0: 企画フェーズ
        step_components["step0_execute_btn"].click(
            fn=execute_step0_planning,
            inputs=[
                step_components["step0_theme"],
                step_components["step0_mode"]
            ],
            outputs=[
                step_components["step0_query1"],
                step_components["step0_query2"],
                step_components["step0_query3"],
                step_components["step0_angle"]
            ],
            show_progress="full"
        )
        
        # Step 0の出力をStep 1の入力に自動コピー
        step_components["step0_query1"].change(
            fn=lambda x: x,
            inputs=[step_components["step0_query1"]],
            outputs=[step_components["step1_query1"]]
        )
        step_components["step0_query2"].change(
            fn=lambda x: x,
            inputs=[step_components["step0_query2"]],
            outputs=[step_components["step1_query2"]]
        )
        step_components["step0_query3"].change(
            fn=lambda x: x,
            inputs=[step_components["step0_query3"]],
            outputs=[step_components["step1_query3"]]
        )
        
        # Step 1: リサーチ & 台本フェーズ
        step_components["step1_execute_btn"].click(
            fn=execute_step1_scripting,
            inputs=[
                step_components["step0_theme"],  # テーマはStep 0から
                step_components["step0_mode"],   # モードもStep 0から
                step_components["step1_query1"],
                step_components["step1_query2"],
                step_components["step1_query3"],
                step_components["step1_excluded_topics"]
            ],
            outputs=[
                step_components["step1_title"],
                step_components["step1_thumbnail"],
                step_components["step1_description"],
                step_components["step1_script_json"],
                step_components["step1_log"]
            ],
            show_progress="full"
        )
        
        # Step 2: 制作フェーズ
        step_components["step2_execute_btn"].click(
            fn=execute_step2_production,
            inputs=[
                step_components["step1_title"],
                step_components["step1_description"],
                step_components["step1_script_json"],
                step_components["step2_background"],
                step_components["step2_bgm"],
                step_components["step2_bgm_volume"],
                step_components["step2_speed"],
                step_components["step2_spectrum"]
            ],
            outputs=[
                step_components["step2_video"],
                step_components["step2_log"]
            ],
            show_progress="full"
        )
    
    return app


if __name__ == "__main__":
    app = create_ui()
    app.launch()
