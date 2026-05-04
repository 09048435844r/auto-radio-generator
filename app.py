"""自動ラジオ動画生成システム - Gradio Web UI

ブラウザ上でパラメータ調整と動画生成実行ができるWeb UIアプリケーション

v3.5.0 機能:
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
from services.media_processing import ThumbnailGenerator, ThumbnailBackgroundGenerator
from google.genai import types
from app_hitl import create_hitl_tab
from app_hitl_handlers import (
    hitl_execute_research,
    _show_research_preview,
    hitl_approve_research,
    hitl_redo_research,
    hitl_import_research,
    hitl_import_script,
    hitl_execute_scripting,
    hitl_save_script_edits,
    hitl_approve_script,
    hitl_execute_production,
    hitl_regenerate_script,
    _show_script_editor,
    _show_production_output,
    # Gate 2a (Topic Curation) - Phase 2 HITL 施策⑤
    hitl_execute_curation,
    hitl_save_curation_edits,
    hitl_approve_curation,
    _show_curation_editor,
)
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


async def check_api_health() -> tuple[str, str, str]:
    """Check API health for Gemini, Perplexity, and Ollama with actual models from config"""
    app_config = load_config()
    
    gemini_status = "🟡チェック中..."
    perplexity_status = "🟡チェック中..."
    ollama_status = "🟡チェック中..."
    
    try:
        # Gemini health check
        gemini_client = GeminiClient(app_config)
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
        perplexity_client = PerplexityResearcher(app_config)
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
    
    try:
        # Ollama health check
        # Orchestrator が実行時に使う curator_model を ping して表示する。
        # Factory に model_override を渡さないと script_generator.ollama.model
        # （旧デフォルト）にフォールバックし、UI に古いモデル名が出てしまう。
        from services.script_generation.adapters.factory import LLMAdapterFactory
        try:
            curator_model = app_config.yaml.script_generator.orchestrator.curator_model
            ollama_adapter = LLMAdapterFactory.create(
                config=app_config,
                provider="ollama",
                model_override=curator_model or None,
            )
            # Use health_check method from adapter
            is_healthy = await ollama_adapter.health_check()
            if is_healthy:
                ollama_status = f"🟢OK ({ollama_adapter.model_name})"
            else:
                ollama_status = f"🔴Error (接続失敗)"
        except Exception as e:
            error_str = str(e)
            if "connection" in error_str.lower() or "timeout" in error_str.lower():
                ollama_status = f"🔴Error (接続不可: {app_config.yaml.script_generator.ollama.base_url})"
            else:
                ollama_status = f"🔴Error ({str(e)[:50]})"
    except Exception as e:
        ollama_status = "🔴Error (初期化失敗)"
    
    return gemini_status, perplexity_status, ollama_status


def run_api_health_check():
    """Wrapper for async health check with safe event loop handling"""
    try:
        # Preferred path: isolated event loop with no global loop mutation.
        return asyncio.run(check_api_health())
    except RuntimeError:
        # Fallback for environments where asyncio.run is unavailable/unsafe.
        loop = asyncio.new_event_loop()
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


_FACTCHECK_PLACEHOLDER = "*生成完了後にファクトチェック結果が表示されます*"


def _format_factcheck_markdown(output_dir: Optional[str | Path]) -> str:
    """factcheck_report.json を Gradio Markdown 用の文字列に整形する

    output_dir に factcheck_report.json があれば読み込み、信頼度スコアを
    色分けバッジで、issues を severity 別アイコン付きカードで表示する。
    無い場合（FactChecker 無効 or エラー）はその旨を示すメッセージを返す。

    Args:
        output_dir: セッションディレクトリ（factcheck_report.json を含むパス）

    Returns:
        Gradio gr.Markdown(value=...) に渡す文字列
    """
    if not output_dir:
        return _FACTCHECK_PLACEHOLDER
    try:
        report_path = Path(output_dir) / "factcheck_report.json"
        if not report_path.exists():
            return (
                "### 🔍 ファクトチェック結果\n\n"
                "_ファクトチェックは実行されていません_\n"
                "（`config.yaml` の `fact_checker.enabled` を `true` にすると有効化）"
            )

        from core.models.fact_check_report import FactCheckReport
        report = FactCheckReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
    except Exception as e:
        return f"### 🔍 ファクトチェック結果\n\n_読み込みエラー: {e}_"

    band = report.confidence_band()
    band_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[band]
    band_label = {
        "green": "良好（80以上）",
        "yellow": "要確認（60-79）",
        "red": "要修正（59以下）",
    }[band]

    lines: list[str] = []
    lines.append("### 🔍 ファクトチェック結果\n")
    lines.append(
        f"**全体信頼度**: {band_emoji} **{report.overall_confidence}/100** "
        f"_({band_label})_\n"
    )
    if report.summary:
        lines.append(f"\n> {report.summary}\n")

    if not report.issues:
        lines.append("\n✅ **重大な問題は検出されませんでした**\n")
        return "\n".join(lines)

    sev_icons = {"high": "🔴", "medium": "🟡", "low": "🔵"}
    sev_labels = {"high": "重大", "medium": "中", "low": "軽微"}
    counts = {
        "high": len(report.issues_by_severity("high")),
        "medium": len(report.issues_by_severity("medium")),
        "low": len(report.issues_by_severity("low")),
    }
    lines.append(
        f"\n**検出された問題**: 🔴 重大 {counts['high']}件 ／ "
        f"🟡 中 {counts['medium']}件 ／ 🔵 軽微 {counts['low']}件\n"
    )

    # Phase 3B: 自動修正件数を集計表示
    auto_fixed_count = sum(1 for i in report.issues if getattr(i, "auto_fixed", False))
    if auto_fixed_count > 0:
        lines.append(f"\n**自動修正**: ✅ {auto_fixed_count}件 適用済み\n")

    for i, issue in enumerate(report.issues, 1):
        icon = sev_icons.get(issue.severity, "⚪")
        label = sev_labels.get(issue.severity, issue.severity)
        is_fixed = bool(getattr(issue, "auto_fixed", False))
        fixed_text = getattr(issue, "fixed_text", None)

        if is_fixed and fixed_text:
            # Phase 3B: 修正済みカードは「修正前 → 修正後」表示
            lines.append(
                f"\n---\n\n"
                f"#### {icon} #{i} [{label}] ✅ 修正済み\n"
                f"**問題点**: {issue.issue}\n\n"
                f"**修正前**:\n> {issue.script_quote}\n\n"
                f"**修正後**:\n> {fixed_text}\n"
            )
        else:
            # 未修正カードは従来通り「問題点 + 修正案」表示
            lines.append(
                f"\n---\n\n"
                f"#### {icon} #{i} [{label}]\n"
                f"**該当箇所**:\n> {issue.script_quote}\n\n"
                f"**問題点**: {issue.issue}\n\n"
                f"**修正案**: {issue.suggestion or '_（提案なし）_'}\n"
            )
    return "\n".join(lines)


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
    research_import_filepath: Optional[str] = None,
    progress=gr.Progress()
) -> tuple[str | None, str, str, str, str, str, Optional[ThumbnailRegenerationState], str]:
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
    # 入力検証（リサーチインポート時はテーマ不要）
    if (not theme or not theme.strip()) and not use_mock and not research_import_filepath:
        return None, "エラー: テーマを入力してください。", "", "", "", "YouTube: 未実行", None, _FACTCHECK_PLACEHOLDER

    effective_theme = theme.strip() if theme and theme.strip() else ("Mock run" if use_mock else "Imported Research")
    
    # ジングルパスを解決
    jingle_path = resolve_jingle_path(jingle_choice, jingle_custom_path)
    if jingle_choice != "なし" and not jingle_path:
        append_log(f"[WARNING] ジングルファイルが見つかりません: {jingle_choice}")
    
    # ログをクリア
    clear_logs()
    append_log("自動ラジオ動画生成システム v3.5.0")
    append_log("=" * 40)
    
    if second_mode != "なし":
        append_log(f"[INFO] 第2部モード有効: {research_mode} → {second_mode}")
    if jingle_path:
        append_log(f"[INFO] ジングル有効: {jingle_choice} ({jingle_path})")
    
    # リサーチモードを変換
    mode = RESEARCH_MODE_MAP.get(research_mode)
    second_mode_enum = RESEARCH_MODE_MAP.get(second_mode) if second_mode != "なし" else None
    enable_research = mode is not None
    
    # デバッグ: UIから渡されたllm_providerの値を確認
    append_log(f"[DEBUG] UI llm_provider = {llm_provider}")
    
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
    
    append_log(f"[DEBUG] UIOverrides.llm_provider = {overrides.llm_provider}")
    
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
        research_import_filepath=research_import_filepath or None,
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
            app_config = load_config()
            bg_path = app_config.yaml.paths.background_image
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

        # FactCheck 結果を読み込み（result.output_dir 配下の factcheck_report.json）
        factcheck_md = _format_factcheck_markdown(result.output_dir)

        return (
            str(result.video_path),
            get_logs(),
            cost_report,
            formatted_title,
            formatted_description,
            youtube_status,
            thumbnail_state,
            factcheck_md,
        )
    else:
        error_msg = result.error_message if result.error_message else "動画生成に失敗しました"
        append_log(f"\n❌ {error_msg}")
        # 失敗時でも、途中まで進んでいれば factcheck_report.json が残っている可能性あり
        factcheck_md = _format_factcheck_markdown(getattr(result, "output_dir", None))
        return None, get_logs(), "", "", "", "YouTube: 未実行", None, factcheck_md


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
) -> tuple[str | None, str, str, str, str, str, Optional[ThumbnailRegenerationState], str]:
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
        app_config = load_config(PROJECT_ROOT)
        
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
                
                script_generator = GeminiClient(app_config)
                plan = await script_generator.create_research_plan(theme.strip(), mode, instruction=None)
                
                append_log(f"\n✓ 検索計画作成完了")
                append_log(f"切り口: {plan.angle}")
                append_log(f"\n検索クエリ:")
                for i, q in enumerate(plan.queries, 1):
                    append_log(f"  {i}. {q}")
                
                # Step 1: 複数クエリで並列リサーチ
                progress(0.3, desc="Step 1: 並列リサーチ中...")
                append_log(f"\n== Step 1: 並列リサーチ ({research_mode}) ==")
                
                researcher = PerplexityResearcher(app_config)
                research_result = await researcher.research_multi(plan.queries, mode)
                
                append_log(f"\n✓ 並列リサーチ完了")
                append_log(f"収集した情報: {len(research_result.content)}文字")
            else:
                append_log("リサーチなしで台本生成")
            
            # Step 2: 収集した情報を元に台本生成
            progress(0.7, desc="Step 2: 台本生成中...")
            append_log(f"\n== Step 2: 台本生成 ==")
            
            if not script_generator:
                script_generator = GeminiClient(app_config)
            
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


def research_only(
    theme: str,
    research_mode: str,
    avoid_topics: str = "",
    progress=gr.Progress()
) -> tuple[str, str, str]:
    """リサーチのみを実行してJSONLファイルに保存
    
    Args:
        theme: 動画のテーマ
        research_mode: リサーチモード
        avoid_topics: 避けてほしい話題（除外要件、オプション）
        progress: Gradio進捗バー
    
    Returns:
        (保存パス, ログ出力, フォーマット済みJSON)
    """
    import asyncio
    from services.research import PerplexityResearcher
    from services.script_generation import GeminiClient
    from datetime import datetime
    
    clear_logs()
    append_log("🔍 リサーチのみモード")
    append_log("=" * 40)
    append_log("リサーチ結果を保存します")
    
    if not theme or not theme.strip():
        return "", "エラー: テーマを入力してください。", ""
    
    try:
        app_config = load_config(PROJECT_ROOT)
        mode = RESEARCH_MODE_MAP.get(research_mode)
        
        if not mode:
            return "", "エラー: リサーチモードを選択してください。", ""
        
        async def execute_research():
            progress(0.1, desc="Step 0: AIが検索計画を作成中...")
            append_log(f"\n== Step 0: 検索計画作成 ==")
            append_log(f"テーマ: {theme.strip()}")
            
            script_generator = GeminiClient(app_config)
            plan = await script_generator.create_research_plan(theme.strip(), mode, instruction=None)
            
            append_log(f"\n✓ 検索計画作成完了")
            append_log(f"切り口: {plan.angle}")
            append_log(f"\n検索クエリ:")
            for i, q in enumerate(plan.queries, 1):
                append_log(f"  {i}. {q}")
            
            progress(0.5, desc="Step 1: 並列リサーチ中...")
            append_log(f"\n== Step 1: 並列リサーチ ({research_mode}) ==")
            
            researcher = PerplexityResearcher(app_config)
            avoid = avoid_topics.strip() if avoid_topics and avoid_topics.strip() else None
            if avoid:
                append_log(f"除外要件: {avoid}")
            research_result = await researcher.research_multi(plan.queries, mode, avoid_topics=avoid)
            
            append_log(f"\n✓ 並列リサーチ完了")
            append_log(f"収集した情報: {len(research_result.content)}文字")
            
            return research_result, plan
        
        research_result, plan = asyncio.run(execute_research())
        
        progress(0.9, desc="リサーチ結果を保存中...")
        
        # 保存先ディレクトリ
        research_dir = PROJECT_ROOT / "data" / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイル名（タイムスタンプ付き）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_theme = "".join(c for c in theme.strip()[:30] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
        filename = f"research_{timestamp}_{safe_theme}.jsonl"
        filepath = research_dir / filename
        
        # JSONL形式で保存（ResearchSourceオブジェクトを辞書に変換）
        sources_list = [
            {
                "url": source.url,
                "title": source.title
            }
            for source in research_result.sources
        ]
        
        research_data = {
            "timestamp": datetime.now().isoformat(),
            "theme": theme.strip(),
            "mode": research_mode,
            "angle": plan.angle,
            "queries": plan.queries,
            "content": research_result.content,
            "sources": sources_list
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json.dumps(research_data, ensure_ascii=False) + "\n")
        
        progress(1.0, desc="完了!")
        append_log(f"\n✓ リサーチ結果を保存しました")
        append_log(f"保存先: {filepath}")
        append_log("\n" + "=" * 40)
        append_log("✓ リサーチのみモード完了")
        append_log("保存されたリサーチ結果は手動モードで利用できます")
        
        # JSON整形（デバッグ表示用）
        formatted_json = json.dumps(research_data, indent=2, ensure_ascii=False)
        
        # \nエスケープシーケンスを実際の改行に変換（表示用）
        formatted_json = formatted_json.replace('\\n', '\n')
        
        return str(filepath), get_logs(), formatted_json
        
    except Exception as e:
        error_msg = f"リサーチ中にエラーが発生しました: {str(e)}"
        append_log(f"\n❌ {error_msg}")
        import traceback
        append_log(f"\n詳細:\n{traceback.format_exc()}")
        return "", get_logs(), ""


def load_research_json_file(filepath: str | None) -> str:
    """既存のリサーチJSONファイルを読み込んで整形表示
    
    Args:
        filepath: JSONLファイルのパス
    
    Returns:
        フォーマット済みJSON文字列
    """
    if not filepath:
        return ""
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
            
        # JSONL形式（1行JSON）をパース
        data = json.loads(content)
        
        # 整形してJSON文字列化
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        
        # \nエスケープシーケンスを実際の改行に変換（表示用）
        # JSON文字列内の\"\\n\"を実際の改行文字に置換
        formatted = formatted.replace('\\n', '\n')
        
        return formatted
    
    except json.JSONDecodeError as e:
        return f"❌ JSON解析エラー: {str(e)}"
    except Exception as e:
        return f"❌ ファイル読み込みエラー: {str(e)}"


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
        app_config = load_config(PROJECT_ROOT)
        
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
        renderer = FfmpegRenderer(app_config)
        
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


def clear_comparison_data() -> tuple[str, list]:
    """比較データをクリア
    
    Returns:
        (メッセージ, 空のリスト)
    """
    return "*比較データをクリアしました。新しいモデルで台本を生成してください。*", []


def restore_script_from_comparison(selected_model: str, comparison_state: list) -> tuple[str, str]:
    """選択したモデルの台本を復元
    
    Args:
        selected_model: 選択されたモデル名（"gemini-2.5-pro (1234ターン)"形式）
        comparison_state: 比較セッションの状態
    
    Returns:
        (script_output用JSON, script_editor用JSON)
    """
    if not selected_model or not comparison_state:
        return "", ""
    
    # モデル名を抽出（"gemini-2.5-pro (1234ターン)" → "gemini-2.5-pro"）
    model_name = selected_model.split(" (")[0]
    
    # comparison_stateから該当モデルのデータを取得
    for data in comparison_state:
        if data["model_name"] == model_name:
            return data["script_json"], data["script_json"]
    
    return "", ""


def export_comparison_session(
    comparison_state: list,
    research_input: str,
    theme: str
) -> tuple[str, dict]:
    """比較セッションを一括エクスポート
    
    Args:
        comparison_state: 比較セッションの状態
        research_input: リサーチデータ
        theme: テーマ/タイトル
    
    Returns:
        (ステータスメッセージ, Textbox更新用dict)
    """
    from services.comparison_session import save_comparison_session
    from datetime import datetime
    
    if not comparison_state or len(comparison_state) < 2:
        return (
            "エラー: 比較データが不足しています（2つ以上のモデルが必要）",
            gr.Textbox(visible=True)
        )
    
    try:
        # Type validation
        if not isinstance(research_input, str):
            return (
                f"エラー: research_inputが文字列ではありません（型: {type(research_input).__name__}）",
                gr.Textbox(visible=True)
            )
        
        if not isinstance(theme, str):
            return (
                f"エラー: themeが文字列ではありません（型: {type(theme).__name__}）",
                gr.Textbox(visible=True)
            )
        
        app_config = load_config(PROJECT_ROOT)
        
        # リサーチデータの構造化
        research_data = {
            "theme": theme,
            "content": research_input,
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存実行
        save_path = save_comparison_session(
            comparison_state=comparison_state,
            research_data=research_data,
            theme=theme,
            config=app_config
        )
        
        return (
            f"✓ 比較セッションを保存しました\n保存先: {save_path}",
            gr.Textbox(visible=True)
        )
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return (
            f"エラー: {str(e)}\n\n詳細:\n{error_detail}",
            gr.Textbox(visible=True)
        )


def load_latest_research() -> tuple[str, str]:
    """最新のリサーチデータを読み込む
    
    Returns:
        (research_content, theme)
    """
    research_dir = PROJECT_ROOT / "data" / "research"
    
    if not research_dir.exists():
        return "", ""
    
    # 最新のJSONLファイルを取得
    jsonl_files = sorted(research_dir.glob("research_*.jsonl"), reverse=True)
    
    if not jsonl_files:
        return "", ""
    
    latest_file = jsonl_files[0]
    
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            data = json.loads(f.readline())
        
        return data["content"], data["theme"]
    except Exception as e:
        print(f"[ERROR] Failed to load research data: {e}")
        return "", ""


def generate_script_from_research(
    research_text: str,
    theme: str,
    model_name: str,
    comparison_state: list,
    progress=gr.Progress()
) -> tuple[str, str, str, list, dict]:
    """リサーチ結果から台本を生成
    
    Args:
        research_text: Perplexity等のリサーチ結果
        theme: テーマ/タイトル
        model_name: 使用するモデル名
        comparison_state: 比較用状態
    
    Returns:
        (台本JSON, 台本JSON, 比較レポート, 更新された状態, ドロップダウン更新用dict)
    """
    import asyncio
    
    # Type validation
    if not isinstance(research_text, str):
        error_msg = f"エラー: research_textが文字列ではありません（型: {type(research_text).__name__}）"
        return error_msg, error_msg, "", comparison_state, gr.Dropdown()
    
    if not isinstance(theme, str):
        error_msg = f"エラー: themeが文字列ではありません（型: {type(theme).__name__}）"
        return error_msg, error_msg, "", comparison_state, gr.Dropdown()
    
    # 入力検証
    if not research_text or not research_text.strip():
        error_msg = "エラー: リサーチ結果を入力してください。"
        return error_msg, error_msg, "", comparison_state, gr.Dropdown()
    
    if not theme or not theme.strip():
        error_msg = "エラー: テーマ/タイトルを入力してください。"
        return error_msg, error_msg, "", comparison_state, gr.Dropdown()
    
    try:
        # ログをクリア
        clear_logs()
        append_log("台本生成ツール v3.5.0")
        append_log("=" * 40)
        append_log("リサーチ結果から台本を生成します...")
        
        progress(0.2, desc="設定を読み込み中...")
        
        # 設定を読み込み
        app_config = load_config(PROJECT_ROOT)
        
        # モデル名からプロバイダーを推定
        from services.script_generation.llm_factory import get_provider_from_model_name
        try:
            provider = get_provider_from_model_name(model_name)
            append_log(f"選択されたモデル: {model_name} ({provider.upper()})")
        except ValueError as e:
            error_msg = f"エラー: {str(e)}"
            append_log(error_msg)
            return error_msg, error_msg, "", comparison_state, gr.Dropdown()
        
        script_generator = create_script_generator(app_config, provider=provider)
        
        progress(0.4, desc="リサーチデータを処理中...")
        
        # リサーチ結果を作成（簡易的な実装）
        research_result = ResearchResult(
            topic=theme.strip(),
            mode="trivia",  # マニュアル入力はトリビアモードとして扱う
            content=research_text.strip(),
            sources=[]  # 手動入力の場合はソースなし
        )
        
        progress(0.6, desc="台本を生成中...")
        
        # 台本を生成（非同期処理）
        async def generate_async():
            return await script_generator.generate(theme.strip(), research_result)
        
        script = asyncio.run(generate_async())
        
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
        
        # コスト表示
        if hasattr(script_generator, 'last_usage') and script_generator.last_usage:
            usage = script_generator.last_usage
            from services.cost_calculator import CostCalculator
            calculator = CostCalculator(app_config)
            cost_lines = calculator.format_llm_cost_log(usage)
            for line in cost_lines:
                append_log(line)
        
        script_json = json.dumps(script_dict, ensure_ascii=False, indent=2)
        
        # 比較用に保存してレポート生成
        comparison_report_md = ""
        updated_state = comparison_state
        
        if hasattr(script_generator, 'last_usage') and script_generator.last_usage:
            # 同じモデルのデータは上書き（重複排除）
            updated_state = [
                d for d in comparison_state 
                if d["model_name"] != model_name
            ]
            
            # 新しいデータを追加
            updated_state.append({
                "model_name": model_name,
                "script_json": script_json,
                "usage": script_generator.last_usage
            })
            
            # 比較レポート生成（2つ以上のデータがある場合）
            if len(updated_state) >= 2:
                from services.comparison_report import generate_comparison_report
                comparison_report_md = generate_comparison_report(updated_state, app_config)
            else:
                # スケーラブルな文言（上限を前提としない）
                comparison_report_md = f"*現在 {len(updated_state)} 個のモデルで台本を生成済み。比較には2つ以上必要です。*"
        else:
            comparison_report_md = "*使用量情報が取得できませんでした*"
        
        # ドロップダウン選択肢を生成
        dropdown_choices = []
        for data in updated_state:
            script = json.loads(data["script_json"])
            turn_count = len(script.get("dialogue", []))
            dropdown_choices.append(f"{data['model_name']} ({turn_count}ターン)")
        
        return script_json, script_json, comparison_report_md, updated_state, gr.Dropdown(choices=dropdown_choices, value=None)
        
    except Exception as e:
        error_msg = f"台本生成中にエラーが発生しました: {str(e)}"
        append_log(f"❌ {error_msg}")
        import traceback
        append_log(f"\n詳細:\n{traceback.format_exc()}")
        return error_msg, error_msg, "", comparison_state, gr.Dropdown()


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
        app_config = load_config()
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
        log_messages.append(f"❌ エラー発生: {str(e)}")
        log_messages.append(f"詳細:\n{error_detail}")
        return None, None, None, None, "\n".join(log_messages)


async def regenerate_thumbnail_background_async(
    state: Optional[ThumbnailRegenerationState]
) -> tuple[Optional[str], Optional[str], str]:
    """Regenerate thumbnail background using FLUX.1
    
    Args:
        state: Thumbnail regeneration state
    
    Returns:
        tuple: (thumbnail_bg_path, thumbnail_path, log_message)
    """
    log_messages = []
    
    if state is None:
        return None, None, "⚠️ 動画生成が完了していません。先にメインの動画生成を実行してください。"
    
    # Validate required fields
    required_fields = ['theme', 'output_dir', 'background_path', 'base_title']
    missing_fields = [field for field in required_fields if not getattr(state, field, None)]
    if missing_fields:
        return None, None, f"⚠️ 必要な情報が不足しています: {', '.join(missing_fields)}"
    
    try:
        log_messages.append("🎨 サムネイル背景を再生成中（FLUX.1）...")
        log_messages.append(f"テーマ: {state.theme}")
        
        app_config = load_config()
        
        # Generate background
        thumbnail_bg_generator = ThumbnailBackgroundGenerator(app_config)
        output_dir = Path(state.output_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        thumbnail_bg_path = output_dir / f"thumbnail_bg_regenerated_{timestamp}.png"
        
        # Use script summary or theme
        script_summary = state.script_summary[:300] if state.script_summary else state.theme
        
        background_image = await thumbnail_bg_generator.generate_background(
            theme=state.theme,
            script_summary=script_summary,
            output_path=thumbnail_bg_path,
            topic_title=state.base_title
        )
        
        log_messages.append(f"✓ 背景生成完了: {background_image.name}")
        
        # Regenerate thumbnail with new background
        log_messages.append("🖼️ 新しい背景でサムネイルを生成中...")
        thumbnail_generator = ThumbnailGenerator()
        thumbnail_path, video_title, thumbnail_title = thumbnail_generator.regenerate_with_new_title(
            theme=state.theme,
            script_summary=script_summary,
            output_dir=state.output_dir,
            background_path=str(background_image),
            base_title=state.base_title,
            generation_count=state.generation_count
        )
        
        log_messages.append(f"✓ サムネイル生成完了: {Path(thumbnail_path).name}")
        log_messages.append(f"動画タイトル: {video_title}")
        log_messages.append(f"サムネイル文字: {thumbnail_title}")
        
        # Return consistent str types for both paths
        return str(background_image), str(thumbnail_path), "\n".join(log_messages)
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        log_messages.append(f"❌ エラー発生: {str(e)}")
        log_messages.append(f"詳細:\n{error_detail}")
        return None, None, "\n".join(log_messages)


def regenerate_thumbnail_background(state):
    """Sync wrapper for async function"""
    return asyncio.run(regenerate_thumbnail_background_async(state))


def create_generator_tab(saved_settings, assets: dict) -> dict[str, object]:
    """Create Generator tab UI and return component references."""
    # 全自動モードのみ（ステップモードは削除済み）
    with gr.Column(visible=True) as auto_mode_column:
        gr.Markdown("""
        ### 🚀 全自動モード
        テーマを入力するだけで、リサーチから動画生成までを自動実行します。
        """)
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
                            choices=["gemini", "openai", "anthropic", "ollama"],
                            value="ollama",
                            info="台本生成に使用するAIモデルを選択",
                            scale=1,
                        )

                    avoid_topics_input = gr.Textbox(
                        label="避けてほしい話題 (オプション)",
                        placeholder="例: 食事療法 運動不足 (スペースやカンマで区切って複数入力可)",
                        lines=1,
                        info="台本に含めたくないトピックを指定できます",
                    )

                    with gr.Accordion("📂 リサーチデータのインポート（リサーチAPIをスキップ）", open=False):
                        gr.Markdown(
                            "過去に生成した `research_brief.json` を指定すると、"
                            "Perplexity APIの呼び出しをスキップしてコストゼロでリサーチフェーズを完了できます。"
                            "指定しない場合は通常通りAPIでリサーチを実行します。"
                        )
                        research_import_file = gr.File(
                            label="リサーチデータをインポート (任意・research_brief.json)",
                            file_types=[".json"],
                            type="filepath",
                            value=None,
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
                            value=False,
                            info="画面下部に音声の波形を表示",
                            visible=False,
                        )

                with gr.Group(elem_classes="group-container"):
                    gr.Markdown("### 📡 APIヘルスチェック")
                    
                    with gr.Row():
                        gemini_status = gr.Markdown("Gemini: 🟡待機中")
                        perplexity_status = gr.Markdown("Perplexity: 🟡待機中")
                    
                    with gr.Row():
                        ollama_status = gr.Markdown("Ollama: 🟡待機中")
                    
                    check_api_btn = gr.Button("🔍 Check API Status", size="sm", variant="secondary")
                    
                    gr.Markdown(
                        """
                        **使い方:**
                        - 生成前にAPI接続状態を確認できます
                        - 🟢OK: 正常接続 / 🔴Error: 接続不可
                        - エラー時はAPIキーやネットワーク（Ollama: サーバー起動状態）を確認してください
                        """
                    )

                with gr.Group(elem_classes="group-container"):
                    gr.Markdown("### 🎬 生成アクション")
                    
                    youtube_upload_checkbox = gr.Checkbox(
                        label="YouTubeに自動アップロード",
                        value=False,
                        info="動画生成後、自動的にYouTubeにアップロードします",
                    )
                    
                    with gr.Row():
                        generate_btn = gr.Button(
                            "🚀 動画を生成する",
                            variant="primary",
                            size="lg",
                            elem_classes="primary-btn",
                        )
                    
                    with gr.Row():
                        research_only_btn = gr.Button(
                            "🔍 リサーチのみ実行",
                            variant="secondary",
                            size="sm",
                        )
                    
                    research_output = gr.Textbox(
                        label="保存されたリサーチファイル",
                        placeholder="リサーチ実行後にファイルパスが表示されます",
                        interactive=False,
                        visible=False
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

                # ファクトチェック結果（FactCheckAgent の出力を表示）
                gr.Markdown("---")
                with gr.Accordion("🔍 ファクトチェック結果", open=True):
                    factcheck_output = gr.Markdown(value=_FACTCHECK_PLACEHOLDER)

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
                
                with gr.Accordion("🎨 サムネイル背景再生成（FLUX.1）", open=False):
                    gr.Markdown(
                        """
                        **FLUX.1で新しい背景画像を生成**
                        - 動画のテーマに基づいて、インパクトのある背景を自動生成
                        - 生成後、新しいタイトルでサムネイルも再作成されます
                        - ⚠️ Forge APIが起動している必要があります
                        """
                    )
                    
                    regenerate_bg_btn = gr.Button("🎨 背景を再生成（FLUX.1）", variant="primary", size="lg")
                    
                    with gr.Row():
                        with gr.Column():
                            bg_preview = gr.Image(label="生成された背景", interactive=False)
                        with gr.Column():
                            bg_thumbnail_preview = gr.Image(label="新しいサムネイル", interactive=False)
                            bg_status = gr.Textbox(label="処理ログ", lines=5, interactive=False)
        
        # リサーチJSON表示（横いっぱいに表示）
        with gr.Accordion("🔍 リサーチ結果生データ (JSON)", open=False):
            with gr.Row():
                research_json_file = gr.File(
                    label="既存のリサーチJSONファイルを読み込む (.jsonl)",
                    file_types=[".jsonl", ".json"],
                    type="filepath"
                )
                load_research_json_btn = gr.Button("📂 JSONを読み込む", size="sm")
            research_json_output = gr.Textbox(
                label="Formatted JSON",
                lines=30,
                max_lines=50,
                interactive=False
            )

    return {
        "auto_mode_column": auto_mode_column,
        # 全自動モードコンポーネント
        "theme_input": theme_input,
        "research_mode_dropdown": research_mode_dropdown,
        "llm_provider_dropdown": llm_provider_dropdown,
        "second_mode_dropdown": second_mode_dropdown,
        "jingle_dropdown": jingle_dropdown,
        "jingle_path_input": jingle_path_input,
        "avoid_topics_input": avoid_topics_input,
        "research_import_file": research_import_file,
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
        "ollama_status": ollama_status,
        "check_api_btn": check_api_btn,
        "youtube_upload_checkbox": youtube_upload_checkbox,
        "generate_btn": generate_btn,
        "research_only_btn": research_only_btn,
        "research_output": research_output,
        "research_json_file": research_json_file,
        "load_research_json_btn": load_research_json_btn,
        "research_json_output": research_json_output,
        "video_output": video_output,
        "youtube_url_output": youtube_url_output,
        "log_output": log_output,
        "cost_output": cost_output,
        "title_output": title_output,
        "description_output": description_output,
        "factcheck_output": factcheck_output,
        "regenerate_thumbnail_btn": regenerate_thumbnail_btn,
        "thumbnail_preview": thumbnail_preview,
        "regenerated_title": regenerated_title,
        "regenerated_thumbnail_title": regenerated_thumbnail_title,
        "regenerate_status": regenerate_status,
        "regenerate_bg_btn": regenerate_bg_btn,
        "bg_preview": bg_preview,
        "bg_thumbnail_preview": bg_thumbnail_preview,
        "bg_status": bg_status,
    }


def create_ui() -> gr.Blocks:
    """Gradio UIを作成"""
    
    # 前回の設定を読み込む
    saved_settings = _settings_manager.load()
    app_config = load_config(PROJECT_ROOT)
    publishing_cfg = getattr(app_config.yaml, "publishing", None)
    default_enable_upload = bool(
        publishing_cfg and getattr(publishing_cfg, "enable_upload", False)
    )
    default_footer_text = (
        getattr(publishing_cfg, "footer_text", "") if publishing_cfg else ""
    )
    # アセット一覧を取得
    assets = get_asset_choices()
    
    with gr.Blocks(title="自動ラジオ動画生成システム v3.5.0") as app:
        
        # ヘッダー
        gr.Markdown(
            """
            # 🎙️ 自動ラジオ動画生成システム v3.5.0
            
            **Perplexity** でテーマをリサーチし、**Gemini** が台本を作成。
            **VOICEVOX** で音声合成、**FFmpeg** で動画を生成します。
            """
        )
        
        # サムネイル再作成用State
        thumbnail_state = gr.State(value=None)
        
        generator_components: dict[str, object] = {}
        hitl_components: dict[str, object] = {}
        dashboard_components: dict[str, gr.components.Component] = {}
        settings_components: dict[str, gr.components.Component] = {}

        # タブ切り替え
        with gr.Tabs():
            with gr.TabItem("🚀 全自動モード", id="auto_mode"):
                generator_components = create_generator_tab(saved_settings=saved_settings, assets=assets)
            
            with gr.TabItem("🎯 HITLモード", id="hitl_mode"):
                hitl_components = create_hitl_tab(assets=assets)

            # Tab 3: Dashboard
            with gr.TabItem("📊 ダッシュボード", id="dashboard"):
                dashboard_components = create_dashboard_tab()

            # Tab 4: Settings
            with gr.TabItem("⚙️ 設定", id="settings"):
                settings_components = create_settings_tab(
                    config=app_config,
                    default_upload_enabled=default_enable_upload,
                    default_footer_text=default_footer_text,
                )
        
        # フッター
        gr.Markdown(
            """
            ---
            *自動ラジオ動画生成システム v3.5.0 | Powered by Perplexity, Gemini, VOICEVOX, FFmpeg*
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
            fn=lambda: get_system_status_markdown(app_config),
            inputs=[],
            outputs=[
                settings_components["perplexity_status"],
                settings_components["gemini_status"],
                settings_components["voicevox_status"],
            ],
        )

        app.load(
            fn=lambda: get_system_status_markdown(app_config),
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
                generator_components["youtube_upload_checkbox"],  # 動画生成タブのチェックボックスを使用
                settings_components["footer_text_input"],
                gr.Checkbox(value=False, visible=False),  # use_mock placeholder
                generator_components["second_mode_dropdown"],
                generator_components["jingle_dropdown"],
                generator_components["jingle_path_input"],
                generator_components["research_import_file"],
            ],
            outputs=[
                generator_components["video_output"],
                generator_components["log_output"],
                generator_components["cost_output"],
                generator_components["title_output"],
                generator_components["description_output"],
                generator_components["youtube_url_output"],
                thumbnail_state,  # Stateを更新
                generator_components["factcheck_output"],
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
        
        # サムネイル背景再生成（FLUX.1）
        generator_components["regenerate_bg_btn"].click(
            fn=regenerate_thumbnail_background,
            inputs=[thumbnail_state],
            outputs=[
                generator_components["bg_preview"],
                generator_components["bg_thumbnail_preview"],
                generator_components["bg_status"],
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
                generator_components["factcheck_output"],
            ],
            show_progress="full",
        )
        
        # APIヘルスチェック
        def update_api_status():
            """Update API status display"""
            try:
                gemini_status, perplexity_status, ollama_status = run_api_health_check()
                return (
                    f"Gemini: {gemini_status}",
                    f"Perplexity: {perplexity_status}",
                    f"Ollama: {ollama_status}"
                )
            except Exception as e:
                return (
                    f"Gemini: 🔴Error (チェック失敗)",
                    f"Perplexity: 🔴Error (チェック失敗)",
                    f"Ollama: 🔴Error (チェック失敗)"
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
                generator_components["perplexity_status"],
                generator_components["ollama_status"]
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
        
        # リサーチのみ実行
        generator_components["research_only_btn"].click(
            fn=research_only,
            inputs=[
                generator_components["theme_input"],
                generator_components["research_mode_dropdown"],
                generator_components["avoid_topics_input"],
            ],
            outputs=[
                generator_components["research_output"],
                generator_components["log_output"],
                generator_components["research_json_output"]
            ],
            show_progress="full"
        )
        
        # 既存のリサーチJSONファイルを読み込む
        generator_components["load_research_json_btn"].click(
            fn=load_research_json_file,
            inputs=[generator_components["research_json_file"]],
            outputs=[generator_components["research_json_output"]]
        )
        
        # ========== HITLモードのイベントハンドラ ==========
        
        # Gate 1: Research
        # Step 1: Execute research and populate child components (Column still hidden)
        # Step 2 (.then): Show the preview Column + enable approve button
        # This split avoids a Gradio bug where toggling Column visibility
        # in the same return as child component values causes values to be lost.
        _research_outputs = [
            hitl_components["hitl_session_state"],
            hitl_components["hitl_research_progress"],
            hitl_components["hitl_research_angle"],
            hitl_components["hitl_research_queries"],
            hitl_components["hitl_research_content"],
            hitl_components["hitl_research_sources"],
            hitl_components["hitl_research_brief_state"],
        ]
        hitl_components["hitl_research_btn"].click(
            fn=hitl_execute_research,
            inputs=[
                hitl_components["hitl_theme_input"],
                hitl_components["hitl_mode_dropdown"],
                hitl_components["hitl_session_state"]
            ],
            outputs=_research_outputs
        ).then(
            fn=_show_research_preview,
            inputs=_research_outputs,
            outputs=[
                hitl_components["hitl_research_preview_section"],
                hitl_components["hitl_research_approve_btn"]
            ]
        )
        
        hitl_components["hitl_research_approve_btn"].click(
            fn=hitl_approve_research,
            inputs=[hitl_components["hitl_session_state"]],
            outputs=[
                hitl_components["gate2a_accordion"],
                hitl_components["gate2_accordion"],
                hitl_components["hitl_research_progress"]
            ]
        )
        
        hitl_components["hitl_research_redo_btn"].click(
            fn=hitl_redo_research,
            inputs=[],
            outputs=[
                hitl_components["hitl_research_preview_section"],
                hitl_components["hitl_research_progress"]
            ]
        )
        
        # Import existing research data (import only, no script generation)
        hitl_components["hitl_import_research_btn"].click(
            fn=hitl_import_research,
            inputs=[hitl_components["hitl_import_research_file"]],
            outputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_research_progress"],
                hitl_components["hitl_research_angle"],
                hitl_components["hitl_research_queries"],
                hitl_components["hitl_research_content"],
                hitl_components["hitl_research_sources"],
                hitl_components["hitl_research_brief_state"]
            ]
        ).then(
            fn=_show_research_preview,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_research_progress"],
                hitl_components["hitl_research_angle"],
                hitl_components["hitl_research_queries"],
                hitl_components["hitl_research_content"],
                hitl_components["hitl_research_sources"],
                hitl_components["hitl_research_brief_state"]
            ],
            outputs=[
                hitl_components["hitl_research_preview_section"],
                hitl_components["hitl_research_approve_btn"]
            ]
        )
        
        # -------------------------------------------------------------
        # Gate 2a: Topic Curation (Phase 2 HITL 施策⑤)
        # Two-step pattern to avoid Gradio bug with Column visibility
        # -------------------------------------------------------------
        _curation_outputs = [
            hitl_components["hitl_curation_progress"],
            hitl_components["hitl_curation_topics_editor"],
            hitl_components["hitl_curation_json_editor"],
        ]
        hitl_components["hitl_curation_run_btn"].click(
            fn=hitl_execute_curation,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_curation_provider_dropdown"],
            ],
            outputs=_curation_outputs,
        ).then(
            fn=_show_curation_editor,
            inputs=_curation_outputs,
            outputs=[hitl_components["hitl_curation_editor_section"]],
        )

        # Re-run Curator (same as run button)
        hitl_components["hitl_curation_reset_btn"].click(
            fn=hitl_execute_curation,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_curation_provider_dropdown"],
            ],
            outputs=_curation_outputs,
        ).then(
            fn=_show_curation_editor,
            inputs=_curation_outputs,
            outputs=[hitl_components["hitl_curation_editor_section"]],
        )

        # Save edited topics to session (curation_result.json)
        hitl_components["hitl_curation_save_btn"].click(
            fn=hitl_save_curation_edits,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_curation_topics_editor"],
                hitl_components["hitl_curation_json_editor"],
            ],
            outputs=[hitl_components["hitl_curation_save_status"]],
        )

        # Approve curation: save then open Gate 2
        hitl_components["hitl_curation_approve_btn"].click(
            fn=hitl_save_curation_edits,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_curation_topics_editor"],
                hitl_components["hitl_curation_json_editor"],
            ],
            outputs=[hitl_components["hitl_curation_save_status"]],
        ).then(
            fn=hitl_approve_curation,
            inputs=[hitl_components["hitl_session_state"]],
            outputs=[
                hitl_components["gate2_accordion"],
                hitl_components["hitl_curation_save_status"],
            ],
        )

        # Gate 2: Scripting (Two-step pattern to avoid Gradio bug)
        hitl_components["hitl_script_generate_btn"].click(
            fn=hitl_execute_scripting,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_provider_dropdown"],
                hitl_components["hitl_avoid_topics"]
            ],
            outputs=[
                hitl_components["hitl_script_progress"],
                hitl_components["hitl_script_turns_editor"],
                hitl_components["hitl_script_json_editor"],
                hitl_components["hitl_script_title"],
                hitl_components["hitl_script_thumbnail_title"],
                hitl_components["hitl_script_description"],
            ]
        ).then(
            fn=_show_script_editor,
            inputs=[
                hitl_components["hitl_script_progress"],
                hitl_components["hitl_script_turns_editor"],
                hitl_components["hitl_script_title"],
            ],
            outputs=[
                hitl_components["hitl_script_editor_section"],
                hitl_components["hitl_script_approve_btn"],
            ]
        )
        
        # Import existing script data (Two-step pattern)
        hitl_components["hitl_import_script_btn"].click(
            fn=hitl_import_script,
            inputs=[hitl_components["hitl_import_script_file"]],
            outputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_script_progress"],
                hitl_components["hitl_script_turns_editor"],
                hitl_components["hitl_script_json_editor"],
                hitl_components["hitl_script_title"],
                hitl_components["hitl_script_thumbnail_title"],
                hitl_components["hitl_script_description"],
            ]
        ).then(
            fn=_show_script_editor,
            inputs=[
                hitl_components["hitl_script_progress"],
                hitl_components["hitl_script_turns_editor"],
                hitl_components["hitl_script_title"],
            ],
            outputs=[
                hitl_components["hitl_script_editor_section"],
                hitl_components["hitl_script_approve_btn"],
            ]
        )
        
        hitl_components["hitl_script_save_btn"].click(
            fn=hitl_save_script_edits,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_script_turns_editor"],
                hitl_components["hitl_script_title"],
                hitl_components["hitl_script_thumbnail_title"],
                hitl_components["hitl_script_description"]
            ],
            outputs=[hitl_components["hitl_script_save_status"]]
        )
        
        hitl_components["hitl_script_approve_btn"].click(
            fn=hitl_approve_script,
            inputs=[hitl_components["hitl_session_state"]],
            outputs=[
                hitl_components["gate3_accordion"],
                hitl_components["hitl_script_progress"]
            ]
        )
        
        hitl_components["hitl_script_regenerate_btn"].click(
            fn=hitl_regenerate_script,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_provider_dropdown"],
                hitl_components["hitl_avoid_topics"]
            ],
            outputs=[
                hitl_components["hitl_script_progress"],
                hitl_components["hitl_script_turns_editor"],
                hitl_components["hitl_script_json_editor"],
                hitl_components["hitl_script_title"],
                hitl_components["hitl_script_thumbnail_title"],
                hitl_components["hitl_script_description"],
            ]
        ).then(
            fn=_show_script_editor,
            inputs=[
                hitl_components["hitl_script_progress"],
                hitl_components["hitl_script_turns_editor"],
                hitl_components["hitl_script_title"],
            ],
            outputs=[
                hitl_components["hitl_script_editor_section"],
                hitl_components["hitl_script_approve_btn"],
            ]
        )
        
        # Gate 3: Production (Two-step pattern to avoid Gradio bug)
        hitl_components["hitl_render_btn"].click(
            fn=hitl_execute_production,
            inputs=[
                hitl_components["hitl_session_state"],
                hitl_components["hitl_bg_dropdown"],
                hitl_components["hitl_bgm_dropdown"],
                hitl_components["hitl_speed_slider"],
                hitl_components["hitl_bgm_volume_slider"]
            ],
            outputs=[
                hitl_components["hitl_render_progress"],
                hitl_components["hitl_video_output"],
                hitl_components["hitl_video_file"],
                hitl_components["hitl_audio_output"],
                hitl_components["hitl_subtitle_file"],
                hitl_components["hitl_metadata_output"]
            ]
        ).then(
            fn=_show_production_output,
            inputs=[
                hitl_components["hitl_render_progress"],
                hitl_components["hitl_video_output"],
            ],
            outputs=[
                hitl_components["hitl_output_section"],
            ]
        )
    
    return app


if __name__ == "__main__":
    app = create_ui()
    app.queue()  # Enable queue for proper async handling
    app.launch()
