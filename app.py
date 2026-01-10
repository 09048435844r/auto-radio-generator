"""自動ラジオ動画生成システム - Gradio Web UI

ブラウザ上でパラメータ調整と動画生成実行ができるWeb UIアプリケーション

機能:
- Perplexityによるテーマのリサーチ（3モード: ディベート/世間の声/トリビア）
- Geminiによる3部構成の台本生成（本題70%/リスナーメール20%/エンディング10%）
- VOICEVOXによる音声合成
- FFmpegによる動画生成（音声スペクトラム可視化対応）
"""
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr
from workflow import UIOverrides, run_workflow_sync, WorkflowResult, scan_assets, create_script_generator, load_config
from core.models import Script
from core.interfaces import ResearchResult
from core.settings_manager import SettingsManager, UserSettings
import json


# ログメッセージを蓄積するためのグローバル変数
_log_messages: list[str] = []

# 設定マネージャー
_settings_manager = SettingsManager()


def clear_logs():
    """ログをクリア"""
    global _log_messages
    _log_messages = []


def append_log(msg: str):
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
    "リサーチなし": None
}


def get_asset_choices() -> dict[str, list[str]]:
    """アセットの選択肢を取得"""
    assets = scan_assets(PROJECT_ROOT)
    return assets


def generate_video(
    theme: str,
    research_mode: str,
    background_image: str,
    bgm_file: str,
    bgm_volume: float,
    fade_time: float,
    speed_scale: float,
    enable_spectrum: bool,
    progress=gr.Progress()
) -> tuple[str | None, str, str, str, str]:
    """動画生成を実行
    
    Args:
        theme: 動画のテーマ
        research_mode: リサーチモード
        background_image: 背景画像ファイル名
        bgm_file: BGMファイル名
        bgm_volume: BGM音量 (0.0-0.5)
        fade_time: フェードイン/アウト時間 (秒)
        speed_scale: 音声スピード (0.8-1.5)
        enable_spectrum: スペクトラム表示
        progress: Gradio進捗バー
    
    Returns:
        (動画パス, ログ出力, コストレポート, タイトル, 概要欄)
    """
    # 入力検証
    if not theme or not theme.strip():
        return None, "エラー: テーマを入力してください。", "", "", ""
    
    # ログをクリア
    clear_logs()
    append_log("自動ラジオ動画生成システム v3.0")
    append_log("=" * 40)
    
    # リサーチモードを変換
    mode = RESEARCH_MODE_MAP.get(research_mode)
    enable_research = mode is not None
    
    # オーバーライド設定を作成
    overrides = UIOverrides(
        research_mode=mode,
        enable_research=enable_research,
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
    
    # ワークフロー実行
    result: WorkflowResult = run_workflow_sync(
        theme=theme.strip(),
        overrides=overrides,
        log_callback=log_callback,
        progress_callback=progress_callback
    )
    
    # 成功時に設定を保存
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
        
        return str(result.video_path), get_logs(), cost_report, formatted_title, formatted_description
    else:
        error_msg = result.error_message or "不明なエラーが発生しました"
        append_log("")
        append_log(f"❌ 生成失敗: {error_msg}")
        return None, get_logs(), "", "", ""


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
            dialogue_lines.append(DialogueLine(
                speaker_id=line_dict.get("speaker_id", "main"),
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
            
            result = await voicevox.synthesize_script(
                script=script,
                output_dir=output_dir,
                speed_scale=1.1,  # デフォルト話速
                progress_callback=synthesis_progress
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
        
        # FfmpegRenderer作成
        progress(0.2, desc="レンダラーを初期化中...")
        renderer = FfmpegRenderer(config)
        
        # 非同期処理を実行
        async def render():
            progress(0.3, desc="動画をレンダリング中...")
            append_log(f"\n== 動画レンダリング ==")
            
            # レンダリング実行
            result = await renderer.render(
                audio_path=audio_file,
                subtitle_path=subtitle_file,
                background_path=background_file,
                bgm_path=bgm_path,
                output_path=video_path,
                bgm_volume=0.15,  # デフォルト音量
                fade_in_sec=3.0,
                fade_out_sec=3.0,
                enable_spectrum=True  # スペクトラム表示
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
        append_log("台本生成ツール v3.0")
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
                    "speaker_id": line.speaker_id,
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


def create_ui() -> gr.Blocks:
    """Gradio UIを作成"""
    
    # 前回の設定を読み込む
    saved_settings = _settings_manager.load()
    
    # アセット一覧を取得
    assets = get_asset_choices()
    
    with gr.Blocks(
        title="自動ラジオ動画生成システム v3.0"
    ) as app:
        
        # ヘッダー
        gr.Markdown(
            """
            # 🎙️ 自動ラジオ動画生成システム v3.0
            
            **Perplexity** でテーマをリサーチし、**Gemini** が台本を作成。
            **VOICEVOX** で音声合成、**FFmpeg** で動画を生成します。
            """
        )
        
        # タブ切り替え
        with gr.Tabs() as tabs:
            # Tab 1: 自動生成 (Classic)
            with gr.TabItem("🚀 自動生成 (Classic)", id="classic"):
                with gr.Row():
                    # ========== 左カラム: 設定パネル ==========
                    with gr.Column(scale=1):
                        gr.Markdown("### ⚙️ 設定パネル")
                        
                        # テーマ入力
                        theme_input = gr.Textbox(
                            label="テーマ",
                            placeholder="例: AIの未来について / 最近のゲーム事情 / 宇宙開発の最新動向",
                            lines=2,
                            info="動画で話すテーマを入力してください（必須）"
                        )
                        
                        # リサーチモード選択
                        research_mode_dropdown = gr.Dropdown(
                            label="リサーチモード",
                            choices=list(RESEARCH_MODE_MAP.keys()),
                            value=saved_settings.research_mode,
                            info="Perplexityによるリサーチの方向性を選択"
                        )
                        
                        gr.Markdown("### 🎨 素材選択")
                        
                        with gr.Row():
                            # 背景画像選択
                            background_dropdown = gr.Dropdown(
                                label="背景画像",
                                choices=assets.get("backgrounds", ["default.png"]),
                                value=saved_settings.background_image if saved_settings.background_image in assets.get("backgrounds", []) else (assets.get("backgrounds", ["default.png"])[0] if assets.get("backgrounds") else None),
                                info="assets/backgrounds/ 内の画像"
                            )
                            
                            # BGM選択
                            bgm_dropdown = gr.Dropdown(
                                label="BGM",
                                choices=assets.get("bgm", ["default.mp3"]),
                                value=saved_settings.bgm_file if saved_settings.bgm_file in assets.get("bgm", []) else (assets.get("bgm", ["default.mp3"])[0] if assets.get("bgm") else None),
                                info="assets/bgm/ 内の音声"
                            )
                        
                        # アセットプレビュー
                        with gr.Row():
                            # 背景画像プレビュー
                            bg_preview = gr.Image(
                                label="背景画像プレビュー",
                                height=200,
                                interactive=False
                            )
                            
                            # BGMプレビュー
                            bgm_preview = gr.Audio(
                                label="BGMプレビュー",
                                interactive=False
                            )
                        
                        # 素材リスト更新ボタン
                        refresh_assets_btn = gr.Button("🔄 素材リストを更新", size="sm")
                        
                        gr.Markdown("### 🎬 動画設定")
                        
                        # BGM音量スライダー
                        bgm_volume_slider = gr.Slider(
                            label="BGM音量",
                            minimum=0.0,
                            maximum=0.5,
                            value=saved_settings.bgm_volume,
                            step=0.01,
                            info="BGMの音量（0.0〜0.5）"
                        )
                        
                        # フェード時間スライダー
                        fade_time_slider = gr.Slider(
                            label="フェード時間",
                            minimum=1.0,
                            maximum=10.0,
                            value=saved_settings.fade_time,
                            step=0.5,
                            info="BGMのフェードイン/アウト時間（秒）"
                        )
                        
                        # 話速調整スライダー
                        speed_slider = gr.Slider(
                            label="話速 (Speed)",
                            minimum=0.8,
                            maximum=1.5,
                            value=saved_settings.speed_scale,
                            step=0.05,
                            info="音声の再生速度（0.8～1.5）"
                        )
                        
                        # スペクトラム表示
                        spectrum_checkbox = gr.Checkbox(
                            label="音声スペクトラムを表示",
                            value=saved_settings.enable_spectrum,
                            info="画面下部に音声の波形を表示"
                        )
                        
                        # 実行ボタン
                        generate_btn = gr.Button(
                            "🚀 動画を生成する",
                            variant="primary",
                            size="lg"
                        )
                        
                        # 注意事項
                        gr.Markdown(
                            """
                            ### ⚠️ 注意事項
                            - **VOICEVOX** エンジンが起動している必要があります
                            - **Perplexity API Key** と **Gemini API Key** が `.env` に設定されている必要があります
                            - 生成には数分かかる場合があります
                            """
                        )
                    
                    # ========== 右カラム: 結果パネル ==========
                    with gr.Column(scale=1):
                        gr.Markdown("## 📺 結果パネル")
                        
                        # 生成動画プレイヤー
                        video_output = gr.Video(
                            label="生成された動画",
                            height=360
                        )
                        
                        # ログ出力
                        log_output = gr.Textbox(
                            label="処理ログ",
                            lines=12,
                            max_lines=18,
                            interactive=False
                        )
                        
                        # コストレポート表示
                        gr.Markdown("### 📊 API使用量・コスト")
                        cost_output = gr.Markdown(
                            value="*生成完了後に表示されます*"
                        )
                        
                        # メタデータ表示エリア
                        gr.Markdown("### 📝 YouTubeメタデータ")
                        title_output = gr.Textbox(
                            label="タイトル (コピー用)",
                            placeholder="生成完了後に表示されます",
                            interactive=True
                        )
                        description_output = gr.Textbox(
                            label="概要欄・チャプター (一括コピー用)",
                            placeholder="生成完了後に表示されます",
                            lines=15,
                            interactive=True
                        )
            
            # Tab 2: マニュアル制作 (Pro Tools)
            with gr.TabItem("🛠️ マニュアル制作 (Pro Tools)", id="manual"):
                gr.Markdown("### 📝 Step A: リサーチ結果から台本生成")
                
                # リサーチ結果入力欄
                research_input = gr.Textbox(
                    label="Perplexity等のリサーチ結果を貼り付け",
                    placeholder="ここにリサーチ結果のテキストを貼り付けてください...",
                    lines=10,
                    info="Perplexityや他のソースで得たリサーチ結果を貼り付け"
                )
                
                # テーマ/タイトル入力欄
                theme_input_manual = gr.Textbox(
                    label="テーマ/タイトル",
                    placeholder="例: AIの倫理的課題について",
                    info="台本のテーマまたはタイトルを入力してください"
                )
                
                # 台本生成ボタン
                generate_script_btn = gr.Button(
                    "📝 この内容で台本を作成",
                    variant="primary",
                    size="lg"
                )
                
                # 生成結果表示エリア
                script_output = gr.Code(
                    label="生成された台本",
                    language="json",
                    lines=20,
                    interactive=True
                )
                
                gr.Markdown("---")  # 区切り線
                
                # Step B: 音声合成
                gr.Markdown("### 🎤 Step B: 音声合成 (Audio Synthesis)")
                
                # 台本エディタ
                script_editor = gr.Code(
                    label="台本JSON (編集可能) - Step Aで生成された台本を編集できます",
                    language="json",
                    lines=15,
                    interactive=True
                )
                
                # 音声合成ボタン
                synthesize_btn = gr.Button(
                    "🎤 この台本で音声を合成する",
                    variant="primary",
                    size="lg"
                )
                
                # 出力エリア
                with gr.Row():
                    with gr.Column():
                        # 音声プレイヤー
                        audio_output = gr.Audio(
                            label="生成された音声",
                            interactive=False
                        )
                        
                        # 字幕ファイルダウンロード
                        subtitle_output = gr.File(
                            label="字幕ファイル (.ass)",
                            interactive=False
                        )
                    
                    with gr.Column():
                        # ログ/ステータス表示
                        synthesis_log = gr.Textbox(
                            label="処理ログ",
                            lines=10,
                            interactive=False
                        )
                
                gr.Markdown("---")  # 区切り線
                
                # Step C: 動画レンダリング
                gr.Markdown("### 🎬 Step C: 動画書き出し (Rendering)")
                
                with gr.Row():
                    with gr.Column():
                        # 音声ファイル入力
                        audio_input = gr.Audio(
                            label="音声ファイル",
                            sources=["upload"],
                            type="filepath",
                            interactive=True
                        )
                        
                        # 字幕ファイル入力
                        subtitle_input = gr.File(
                            label="字幕ファイル (.ass)",
                            file_types=[".ass"],
                            type="filepath",
                            interactive=True
                        )
                    
                    with gr.Column():
                        # 背景画像入力
                        background_input = gr.Image(
                            label="背景/サムネイル画像 (1920x1080推奨)",
                            sources=["upload"],
                            type="filepath",
                            interactive=True
                        )
                        
                        # BGM選択
                        bgm_dropdown_manual = gr.Dropdown(
                            label="BGM",
                            choices=assets.get("bgm", ["default.mp3"]),
                            value=assets.get("bgm", ["default.mp3"])[0] if assets.get("bgm") else None,
                            info="assets/bgm/ 内の音声"
                        )
                
                # 動画生成ボタン
                render_btn = gr.Button(
                    "🎬 動画を生成する (Render Video)",
                    variant="primary",
                    size="lg"
                )
                
                # 出力エリア
                with gr.Row():
                    with gr.Column():
                        # 完成動画プレビュー
                        video_output_manual = gr.Video(
                            label="完成動画",
                            interactive=False
                        )
                        
                        # 動画ファイルダウンロード
                        video_file_output = gr.File(
                            label="動画ファイルダウンロード",
                            interactive=False
                        )
                    
                    with gr.Column():
                        # ログ/ステータス表示
                        render_log = gr.Textbox(
                            label="処理ログ",
                            lines=10,
                            interactive=False
                        )
                
                # 使い方
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
                    
                    ### 💡 ヒント
                    - リサーチ結果は詳細であるほど、質の高い台本が生成されます
                    - 生成された台本はJSON形式なので、他のツールでも利用可能です
                    - 台本の構成は「本題70%・リスナーメール20%・エンディング10%」の3部構成です
                    - VOICEVOXエンジンが起動している必要があります
                    - 背景画像は1920x1080ピクセルを推奨します
                    """
                )
        
        # フッター
        gr.Markdown(
            """
            ---
            *自動ラジオ動画生成システム v3.0 | Powered by Perplexity, Gemini, VOICEVOX, FFmpeg*
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
        
        refresh_assets_btn.click(
            fn=refresh_assets,
            inputs=[],
            outputs=[background_dropdown, bgm_dropdown]
        )
        
        # アセットプレビューの更新
        def update_bg_preview(filename):
            if filename:
                bg_path = PROJECT_ROOT / "assets" / "backgrounds" / filename
                return str(bg_path) if bg_path.exists() else None
            return None
        
        def update_bgm_preview(filename):
            if filename:
                bgm_path = PROJECT_ROOT / "assets" / "bgm" / filename
                return str(bgm_path) if bgm_path.exists() else None
            return None
        
        background_dropdown.change(
            fn=update_bg_preview,
            inputs=[background_dropdown],
            outputs=[bg_preview]
        )
        
        bgm_dropdown.change(
            fn=update_bgm_preview,
            inputs=[bgm_dropdown],
            outputs=[bgm_preview]
        )
        
        # 動画生成
        generate_btn.click(
            fn=generate_video,
            inputs=[
                theme_input,
                research_mode_dropdown,
                background_dropdown,
                bgm_dropdown,
                bgm_volume_slider,
                fade_time_slider,
                speed_slider,
                spectrum_checkbox
            ],
            outputs=[video_output, log_output, cost_output, title_output, description_output],
            show_progress="full"
        )
        
        # 台本生成 (Step Aの出力をStep Bのエディタにも反映)
        generate_script_btn.click(
            fn=generate_script_from_research,
            inputs=[research_input, theme_input_manual],
            outputs=[script_output, script_editor],  # 両方に出力
            show_progress="full"
        )
        
        # 音声合成 (Step B) - Step Cの入力にも反映
        synthesize_btn.click(
            fn=synthesize_audio_from_script,
            inputs=[script_editor],
            outputs=[audio_output, subtitle_output, synthesis_log, audio_input, subtitle_input],
            show_progress="full"
        )
        
        # 動画レンダリング (Step C)
        render_btn.click(
            fn=render_video_from_assets,
            inputs=[audio_input, subtitle_input, background_input, bgm_dropdown_manual],
            outputs=[video_output_manual, video_file_output, render_log],
            show_progress="full"
        )
    
    return app


def main():
    """メインエントリーポイント"""
    import sys
    import io
    
    # Windows用UTF-8出力設定
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    print("自動ラジオ動画生成システム - Web UI を起動中...")
    print("=" * 50)
    
    app = create_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=None,  # 自動的に空いているポートを検索
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft()
    )


if __name__ == "__main__":
    main()
