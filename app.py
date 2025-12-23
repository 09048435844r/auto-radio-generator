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
from workflow import UIOverrides, run_workflow_sync, WorkflowResult, scan_assets


# ログメッセージを蓄積するためのグローバル変数
_log_messages: list[str] = []


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
    append_log("自動ラジオ動画生成システム v2.1")
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


def create_ui() -> gr.Blocks:
    """Gradio UIを作成"""
    
    # アセット一覧を取得
    assets = get_asset_choices()
    
    with gr.Blocks(
        title="自動ラジオ動画生成システム"
    ) as app:
        
        # ヘッダー
        gr.Markdown(
            """
            # 🎙️ 自動ラジオ動画生成システム v2.1
            
            **Perplexity** でテーマをリサーチし、**Gemini** が台本を作成。
            **VOICEVOX** で音声合成、**FFmpeg** で動画を生成します。
            """
        )
        
        with gr.Row():
            # ========== 左カラム: 設定パネル ==========
            with gr.Column(scale=1):
                gr.Markdown("## ⚙️ 設定パネル")
                
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
                    value="トリビア (雑学)",
                    info="Perplexityによるリサーチの方向性を選択"
                )
                
                gr.Markdown("### 🎨 素材選択")
                
                with gr.Row():
                    # 背景画像選択
                    background_dropdown = gr.Dropdown(
                        label="背景画像",
                        choices=assets.get("backgrounds", ["default.png"]),
                        value=assets.get("backgrounds", ["default.png"])[0] if assets.get("backgrounds") else None,
                        info="assets/backgrounds/ 内の画像"
                    )
                    
                    # BGM選択
                    bgm_dropdown = gr.Dropdown(
                        label="BGM",
                        choices=assets.get("bgm", ["default.mp3"]),
                        value=assets.get("bgm", ["default.mp3"])[0] if assets.get("bgm") else None,
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
                    value=0.15,
                    step=0.01,
                    info="BGMの音量（0.0〜0.5）"
                )
                
                # フェード時間スライダー
                fade_time_slider = gr.Slider(
                    label="フェード時間",
                    minimum=1.0,
                    maximum=10.0,
                    value=3.0,
                    step=0.5,
                    info="BGMのフェードイン/アウト時間（秒）"
                )
                
                # 話速調整スライダー
                speed_slider = gr.Slider(
                    label="話速 (Speed)",
                    minimum=0.8,
                    maximum=1.5,
                    value=1.1,
                    step=0.05,
                    info="音声の再生速度（0.8～1.5）"
                )
                
                # スペクトラム表示
                spectrum_checkbox = gr.Checkbox(
                    label="音声スペクトラムを表示",
                    value=True,
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
        
        # フッター
        gr.Markdown(
            """
            ---
            *自動ラジオ動画生成システム v2.1 | Powered by Perplexity, Gemini, VOICEVOX, FFmpeg*
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
