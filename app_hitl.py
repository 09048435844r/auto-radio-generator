"""HITL (Human-in-the-Loop) UI Components

パイプライン分離アーキテクチャを活用した介入型UIコンポーネント
"""
import gradio as gr
from typing import Optional


def create_hitl_tab(assets: dict) -> dict[str, object]:
    """Create HITL (Human-in-the-Loop) tab UI
    
    Args:
        assets: Asset choices (backgrounds, bgm, etc.)
        
    Returns:
        Dictionary of component references
    """
    # Session state variables
    hitl_session_state = gr.State(value=None)
    hitl_research_brief_state = gr.State(value=None)
    
    gr.Markdown("""
    ## 🎯 HITL モード (Human-in-the-Loop)
    
    各フェーズの間で中間成果物をプレビュー・編集できる介入型ワークフローです。
    リサーチ → 台本作成 → 動画生成の3つのGateを順番に進めていきます。
    """)
    
    # ========== Gate 1: Research & Review ==========
    with gr.Accordion("🔍 Gate 1: Research & Review", open=True) as gate1_accordion:
        gr.Markdown("""
        ### リサーチフェーズ
        テーマを入力してリサーチを実行し、結果をプレビューします。
        """)
        
        # Input Section
        with gr.Row():
            hitl_theme_input = gr.Textbox(
                label="テーマ",
                placeholder="例: 持続血糖測定器CGMについて",
                lines=2,
                scale=2
            )
            hitl_mode_dropdown = gr.Dropdown(
                label="リサーチモード",
                choices=["lecture", "debate", "trivia", "voices", "weekly_digest"],
                value="lecture",
                scale=1
            )
        
        with gr.Row():
            hitl_research_btn = gr.Button(
                "🔍 リサーチを開始",
                variant="primary",
                size="lg",
                scale=2
            )
            with gr.Column(scale=1):
                gr.Markdown("**または**")
                hitl_import_research_file = gr.File(
                    label="既存のリサーチデータをインポート",
                    file_types=[".json"],
                    type="filepath"
                )
                hitl_import_research_btn = gr.Button(
                    "📂 インポート",
                    size="sm"
                )
        
        # Progress & Status
        hitl_research_progress = gr.Textbox(
            label="進捗",
            interactive=False,
            lines=3
        )
        
        # Preview Section (initially hidden)
        with gr.Column(visible=False) as hitl_research_preview_section:
            gr.Markdown("### 📋 リサーチ結果プレビュー")
            
            with gr.Row():
                with gr.Column(scale=1):
                    hitl_research_angle = gr.Textbox(
                        label="切り口 (Angle)",
                        interactive=False,
                        lines=2
                    )
                    hitl_research_queries = gr.Textbox(
                        label="検索クエリ",
                        lines=3,
                        interactive=False
                    )
                with gr.Column(scale=2):
                    hitl_research_content = gr.Textbox(
                        label="リサーチ内容（抜粋）",
                        lines=10,
                        max_lines=20,
                        interactive=False
                    )
            
            hitl_research_sources = gr.Dataframe(
                label="参照元",
                headers=["タイトル", "URL"],
                datatype=["str", "str"],
                interactive=False,
                wrap=True
            )
            
            # Action Buttons
            with gr.Row():
                hitl_research_approve_btn = gr.Button(
                    "✅ このリサーチで台本作成へ進む",
                    variant="primary",
                    size="lg"
                )
                hitl_research_redo_btn = gr.Button(
                    "🔄 リサーチをやり直す",
                    variant="secondary"
                )
    
    # ========== Gate 2: Script Generation & Editing ==========
    with gr.Accordion("📝 Gate 2: Script Generation & Editing", open=False) as gate2_accordion:
        gr.Markdown("""
        ### 台本作成フェーズ
        リサーチ結果から台本を生成し、直接編集できます。
        """)
        
        # Generation Section
        with gr.Row():
            hitl_provider_dropdown = gr.Dropdown(
                label="LLMプロバイダー",
                choices=["gemini", "openai", "anthropic"],
                value="gemini",
                scale=1
            )
            hitl_avoid_topics = gr.Textbox(
                label="避けてほしい話題 (Negative Prompt)",
                placeholder="例: 政治、宗教",
                scale=2
            )
        
        with gr.Row():
            hitl_script_generate_btn = gr.Button(
                "📝 台本を生成",
                variant="primary",
                size="lg",
                scale=2
            )
            with gr.Column(scale=1):
                gr.Markdown("**または**")
                hitl_import_script_file = gr.File(
                    label="既存の台本データをインポート",
                    file_types=[".json"],
                    type="filepath"
                )
                hitl_import_script_btn = gr.Button(
                    "📂 インポートして編集へ",
                    size="sm"
                )
        
        hitl_script_progress = gr.Textbox(
            label="進捗",
            interactive=False,
            lines=3
        )
        
        # Editor Section (initially hidden)
        with gr.Column(visible=False) as hitl_script_editor_section:
            gr.Markdown("### ✏️ 台本エディタ")
            
            # Tabs for different editing modes
            with gr.Tabs():
                with gr.TabItem("📄 テキストエディタ（推奨）"):
                    gr.Markdown("""
                    **編集方法**: 各セリフを直接編集できます。話者（A/B）、テキスト、感情を変更可能です。
                    """)
                    
                    # Dynamic list of dialogue turns (editable)
                    hitl_script_turns_editor = gr.Dataframe(
                        label="台本（セリフ一覧）",
                        headers=["#", "話者", "テキスト", "感情"],
                        datatype=["number", "str", "str", "str"],
                        col_count=(4, "fixed"),
                        row_count=(20, "dynamic"),
                        interactive=True,
                        wrap=True,
                        value=[]  # Initialize with empty list to enable gr.update(value=...)
                    )
                
                with gr.TabItem("🔧 JSONエディタ（上級者向け）"):
                    with gr.Accordion("JSONエディタを開く", open=False):
                        hitl_script_json_editor = gr.Code(
                            label="台本JSON（直接編集）",
                            language="json",
                            lines=25,
                            interactive=True
                        )
            
            # Metadata Editing
            with gr.Row():
                hitl_script_title = gr.Textbox(
                    label="タイトル",
                    interactive=True
                )
                hitl_script_thumbnail_title = gr.Textbox(
                    label="サムネイルタイトル",
                    interactive=True
                )
            
            hitl_script_description = gr.Textbox(
                label="概要",
                lines=3,
                interactive=True
            )
            
            # Action Buttons
            with gr.Row():
                hitl_script_save_btn = gr.Button(
                    "💾 編集内容を保存",
                    variant="primary",
                    size="lg"
                )
                hitl_script_approve_btn = gr.Button(
                    "✅ この台本で動画生成へ進む",
                    variant="primary",
                    size="lg"
                )
                hitl_script_regenerate_btn = gr.Button(
                    "🔄 台本を再生成",
                    variant="secondary"
                )
            
            hitl_script_save_status = gr.Textbox(
                label="保存ステータス",
                interactive=False
            )
    
    # ========== Gate 3: Production (Rendering) ==========
    with gr.Accordion("🎬 Gate 3: Production (Rendering)", open=False) as gate3_accordion:
        gr.Markdown("""
        ### 動画生成フェーズ
        最終的な台本から動画をレンダリングします。
        """)
        
        # Asset Selection
        with gr.Row():
            hitl_bg_dropdown = gr.Dropdown(
                label="背景画像",
                choices=assets.get("backgrounds", []),
                value=assets.get("backgrounds", ["default.png"])[0] if assets.get("backgrounds") else None
            )
            hitl_bgm_dropdown = gr.Dropdown(
                label="BGM",
                choices=assets.get("bgm", []),
                value=assets.get("bgm", ["default.mp3"])[0] if assets.get("bgm") else None
            )
        
        with gr.Row():
            hitl_speed_slider = gr.Slider(
                label="音声スピード",
                minimum=0.8,
                maximum=1.5,
                value=1.0,
                step=0.05
            )
            hitl_bgm_volume_slider = gr.Slider(
                label="BGM音量",
                minimum=0.0,
                maximum=0.5,
                value=0.15,
                step=0.01
            )
        
        hitl_render_btn = gr.Button(
            "🎬 動画を生成",
            variant="primary",
            size="lg"
        )
        
        hitl_render_progress = gr.Textbox(
            label="進捗",
            interactive=False,
            lines=3
        )
        
        # Output Section (initially hidden)
        with gr.Column(visible=False) as hitl_output_section:
            gr.Markdown("### 🎉 完成！")
            
            with gr.Row():
                with gr.Column():
                    hitl_video_output = gr.Video(label="完成動画")
                    hitl_video_file = gr.File(label="動画ファイルダウンロード")
                with gr.Column():
                    hitl_audio_output = gr.Audio(label="音声ファイル")
                    hitl_subtitle_file = gr.File(label="字幕ファイル (.ass)")
            
            hitl_metadata_output = gr.Textbox(
                label="YouTube用メタデータ",
                lines=10,
                interactive=False
            )
    
    return {
        # State variables
        "hitl_session_state": hitl_session_state,
        "hitl_research_brief_state": hitl_research_brief_state,
        
        # Gate 1 components
        "gate1_accordion": gate1_accordion,
        "hitl_theme_input": hitl_theme_input,
        "hitl_mode_dropdown": hitl_mode_dropdown,
        "hitl_research_btn": hitl_research_btn,
        "hitl_import_research_file": hitl_import_research_file,
        "hitl_import_research_btn": hitl_import_research_btn,
        "hitl_research_progress": hitl_research_progress,
        "hitl_research_preview_section": hitl_research_preview_section,
        "hitl_research_angle": hitl_research_angle,
        "hitl_research_queries": hitl_research_queries,
        "hitl_research_content": hitl_research_content,
        "hitl_research_sources": hitl_research_sources,
        "hitl_research_approve_btn": hitl_research_approve_btn,
        "hitl_research_redo_btn": hitl_research_redo_btn,
        
        # Gate 2 components
        "gate2_accordion": gate2_accordion,
        "hitl_provider_dropdown": hitl_provider_dropdown,
        "hitl_avoid_topics": hitl_avoid_topics,
        "hitl_script_generate_btn": hitl_script_generate_btn,
        "hitl_import_script_file": hitl_import_script_file,
        "hitl_import_script_btn": hitl_import_script_btn,
        "hitl_script_progress": hitl_script_progress,
        "hitl_script_editor_section": hitl_script_editor_section,
        "hitl_script_turns_editor": hitl_script_turns_editor,
        "hitl_script_json_editor": hitl_script_json_editor,
        "hitl_script_title": hitl_script_title,
        "hitl_script_thumbnail_title": hitl_script_thumbnail_title,
        "hitl_script_description": hitl_script_description,
        "hitl_script_save_btn": hitl_script_save_btn,
        "hitl_script_approve_btn": hitl_script_approve_btn,
        "hitl_script_regenerate_btn": hitl_script_regenerate_btn,
        "hitl_script_save_status": hitl_script_save_status,
        
        # Gate 3 components
        "gate3_accordion": gate3_accordion,
        "hitl_bg_dropdown": hitl_bg_dropdown,
        "hitl_bgm_dropdown": hitl_bgm_dropdown,
        "hitl_speed_slider": hitl_speed_slider,
        "hitl_bgm_volume_slider": hitl_bgm_volume_slider,
        "hitl_render_btn": hitl_render_btn,
        "hitl_render_progress": hitl_render_progress,
        "hitl_output_section": hitl_output_section,
        "hitl_video_output": hitl_video_output,
        "hitl_video_file": hitl_video_file,
        "hitl_audio_output": hitl_audio_output,
        "hitl_subtitle_file": hitl_subtitle_file,
        "hitl_metadata_output": hitl_metadata_output,
    }
