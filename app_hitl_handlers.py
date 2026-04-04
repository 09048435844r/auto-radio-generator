"""HITL UI Event Handlers

HITLモードのイベントハンドラとバックエンド連動ロジック
"""
import gradio as gr
from pathlib import Path
from typing import Optional, Tuple, List
from datetime import datetime

from core.session_manager import SessionManager
from core.models.artifacts import ResearchBrief
from core.models.script import RadioScriptArtifact, Script, DialogueTurn
from core.models import load_config
from services.pipeline import (
    execute_research_phase,
    execute_scripting_phase,
    execute_production_phase
)
from workflow import ProgressCallback

# Project root
PROJECT_ROOT = Path(__file__).parent


async def hitl_execute_research(
    theme: str,
    mode: str,
    session_state: Optional[str],
    progress=gr.Progress()
) -> Tuple[str, str, str, str, str, List, str]:
    """Execute research phase and return data for preview
    
    NOTE: Column visibility and Button interactivity are handled by a
    separate .then() handler in app.py to avoid a Gradio bug where
    toggling Column visibility in the same return tuple as child
    component values causes child values to be lost.
    
    Args:
        theme: Research theme
        mode: Research mode
        session_state: Current session ID (None for new session)
        progress: Gradio progress bar
        
    Returns:
        Tuple of (session_id, progress_text, angle, queries, content, sources, research_brief_path)
    """
    if not theme or not theme.strip():
        return (
            session_state or "",
            "❌ エラー: テーマを入力してください。",
            "", "", "", [], ""
        )
    
    try:
        # Load config
        config = load_config(PROJECT_ROOT)
        
        # Initialize SessionManager
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state
        )
        
        progress(0.1, desc="セッション初期化中...")
        progress_text = f"セッションID: {session_manager.session_id}\n"
        progress_text += "リサーチを開始します...\n"
        
        # Progress callback
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, description: str):
            progress(ratio, desc=description)
        
        callbacks = ProgressCallback(
            log_callback=log_callback,
            progress_callback=progress_callback
        )
        
        # Execute research phase
        progress(0.2, desc="リサーチフェーズ実行中...")
        research_brief = await execute_research_phase(
            theme=theme,
            mode=mode,
            session_manager=session_manager,
            config=config,
            callbacks=callbacks
        )
        
        progress(0.9, desc="プレビュー準備中...")
        
        # Format preview data
        angle = research_brief.angle
        queries = "\n".join([f"{i+1}. {q}" for i, q in enumerate(research_brief.queries)])
        content = research_brief.research_content[:1000] + "..." if len(research_brief.research_content) > 1000 else research_brief.research_content
        
        # Format sources for DataFrame
        sources = []
        if research_brief.research_sources:
            for source_dict in research_brief.research_sources:
                if isinstance(source_dict, dict):
                    sources.append([
                        source_dict.get("title", ""),
                        source_dict.get("url", "")
                    ])
        
        # Get saved path
        research_brief_path = session_manager.session_dir / "research_brief.json"
        
        progress_text += "\n".join(log_messages[-10:])  # Last 10 log messages
        progress_text += f"\n\n✅ リサーチ完了！"
        
        progress(1.0, desc="完了!")
        
        return (
            session_manager.session_id,  # hitl_session_state
            progress_text,  # hitl_research_progress
            angle,  # hitl_research_angle
            queries,  # hitl_research_queries
            content,  # hitl_research_content
            sources,  # hitl_research_sources
            str(research_brief_path),  # hitl_research_brief_state
        )
        
    except Exception as e:
        import traceback
        error_msg = f"❌ リサーチ中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
        return (
            session_state or "",
            error_msg,
            "", "", "", [], ""
        )


def _show_research_preview(
    session_state: str,
    progress_text: str,
    angle: str,
    queries: str,
    content: str,
    sources: List,
    research_brief_path: str,
) -> Tuple[gr.update, gr.update]:
    """Show research preview section after data is populated
    
    This is called via .then() AFTER hitl_execute_research completes,
    to work around a Gradio bug where toggling Column visibility and
    updating child components in the same return loses child values.
    
    Returns:
        Tuple of (preview_section_visibility, approve_btn_interactivity)
    """
    # If research succeeded (non-empty angle means data exists)
    if angle and progress_text and "❌" not in progress_text:
        return gr.update(visible=True), gr.update(interactive=True)
    else:
        return gr.update(visible=False), gr.update(interactive=False)


def hitl_approve_research(
    session_state: str
) -> Tuple[gr.update, str]:
    """Approve research and open Gate 2
    
    Args:
        session_state: Current session ID
        
    Returns:
        Tuple of (gate2_accordion_update, status_message)
    """
    print(f"[DEBUG] hitl_approve_research called with session_state: '{session_state}'")
    
    if not session_state:
        print("[DEBUG] session_state is empty, returning error")
        return gr.update(open=False), "❌ エラー: セッションが見つかりません。"
    
    print(f"[DEBUG] Opening Gate 2 for session: {session_state}")
    return gr.update(open=True), f"✅ Gate 2を開放しました。台本生成を開始できます。"


def hitl_redo_research() -> Tuple[gr.update, str]:
    """Redo research (reset preview)
    
    Returns:
        Tuple of (preview_section_update, status_message)
    """
    return gr.update(visible=False), "🔄 リサーチをやり直してください。"


async def hitl_import_research(
    filepath: str | None,
    progress=gr.Progress()
) -> Tuple[str, str, str, str, str, List, str]:
    """Import existing research data and display preview (without script generation)
    
    Args:
        filepath: Path to research_brief.json file
        progress: Gradio progress bar
        
    Returns:
        Tuple of (session_id, progress_text, angle, queries, content, sources, research_brief_path)
    """
    if not filepath:
        return (
            "", "❌ エラー: ファイルを選択してください。",
            "", "", "", [], ""
        )
    
    try:
        import json
        from pathlib import Path
        from core.models.artifacts import ResearchBrief
        from core.session_manager import SessionManager
        from core.models import load_config
        
        progress(0.1, desc="リサーチデータを読み込み中...")
        
        # Load research brief from file
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        research_brief = ResearchBrief(**data)
        
        # Create new session for imported data
        config = load_config(PROJECT_ROOT)
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=None  # Create new session
        )
        
        # Save imported research brief to new session
        research_brief_path = session_manager.session_dir / "research_brief.json"
        with open(research_brief_path, 'w', encoding='utf-8') as f:
            json.dump(research_brief.model_dump(), f, ensure_ascii=False, indent=2)
        
        progress(0.3, desc="リサーチデータのインポート完了")
        
        # Format preview data
        angle = research_brief.angle
        queries = "\n".join([f"{i+1}. {q}" for i, q in enumerate(research_brief.queries)])
        content = research_brief.research_content[:1000] + "..." if len(research_brief.research_content) > 1000 else research_brief.research_content
        
        # Format sources for DataFrame
        sources = []
        if research_brief.research_sources:
            for source_dict in research_brief.research_sources:
                if isinstance(source_dict, dict):
                    sources.append([
                        source_dict.get("title", ""),
                        source_dict.get("url", "")
                    ])
        
        progress_text = f"セッションID: {session_manager.session_id}\n"
        progress_text += f"✅ リサーチデータをインポートしました\n"
        progress_text += f"📂 ファイル: {Path(filepath).name}\n\n"
        progress_text += "「このリサーチで台本作成へ進む」ボタンをクリックして台本生成を開始してください。"
        
        progress(1.0, desc="完了!")
        
        return (
            session_manager.session_id,  # hitl_session_state
            progress_text,  # hitl_research_progress
            angle,  # hitl_research_angle
            queries,  # hitl_research_queries
            content,  # hitl_research_content
            sources,  # hitl_research_sources
            str(research_brief_path)  # hitl_research_brief_state
        )
        
    except Exception as e:
        import traceback
        error_msg = f"❌ インポート中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
        return (
            "", error_msg,
            "", "", "", [], ""
        )


async def hitl_import_script(
    filepath: str | None,
    progress=gr.Progress()
) -> Tuple[str, str, gr.update, List, str, str, str, str, gr.update]:
    """Import existing script data and display in editor
    
    Args:
        filepath: Path to script.json file
        progress: Gradio progress bar
        
    Returns:
        Tuple of (session_id, progress_text, editor_section_update, turns_data, 
                  json_data, title, thumbnail_title, description, approve_btn_update)
    """
    if not filepath:
        return (
            "", "❌ エラー: ファイルを選択してください。",
            gr.update(visible=False), [], "", "", "", "", gr.update(interactive=False)
        )
    
    try:
        import json
        from pathlib import Path
        from core.models.script import Script
        from core.session_manager import SessionManager
        
        progress(0.1, desc="台本データを読み込み中...")
        
        # Load script from file
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        script = Script(**data)
        
        # Create new session for imported data
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=None  # Create new session
        )
        
        # Save imported script to new session
        script_path = session_manager.session_dir / "script.json"
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script.model_dump(), f, ensure_ascii=False, indent=2)
        
        progress(0.5, desc="台本データのインポート完了")
        
        # Convert Script to DataFrame format
        turns_data = script_to_dataframe(script)
        
        # Convert Script to JSON
        json_data = script.model_dump_json(indent=2)
        
        # Extract metadata
        title = script.title
        thumbnail_title = script.thumbnail_title
        description = script.description
        
        progress_text = f"セッションID: {session_manager.session_id}\n"
        progress_text += f"✅ 台本データをインポートしました\n"
        progress_text += f"📂 ファイル: {Path(filepath).name}\n"
        progress_text += f"セリフ数: {len(turns_data)}件"
        
        progress(1.0, desc="完了!")
        
        return (
            session_manager.session_id,  # hitl_session_state
            progress_text,  # hitl_script_progress
            gr.update(visible=True),  # hitl_script_editor_section
            turns_data,  # hitl_script_turns_editor
            json_data,  # hitl_script_json_editor
            title,  # hitl_script_title
            thumbnail_title,  # hitl_script_thumbnail_title
            description,  # hitl_script_description
            gr.update(interactive=True)  # hitl_script_approve_btn
        )
        
    except Exception as e:
        import traceback
        error_msg = f"❌ インポート中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
        return (
            "", error_msg,
            gr.update(visible=False), [], "", "", "", "", gr.update(interactive=False)
        )


async def hitl_execute_scripting(
    session_state: str,
    provider: str,
    avoid_topics: str,
    progress=gr.Progress()
) -> Tuple[str, gr.update, List, str, str, str, str, gr.update]:
    """Execute scripting phase and display editor
    
    Args:
        session_state: Current session ID
        provider: LLM provider
        avoid_topics: Topics to avoid
        progress: Gradio progress bar
        
    Returns:
        Tuple of (progress_text, editor_section_update, turns_data, json_data, title, thumbnail_title, description, approve_btn_update)
    """
    if not session_state:
        return (
            "❌ エラー: セッションが見つかりません。まずリサーチを実行してください。",
            gr.update(visible=False),
            [], "", "", "", "", gr.update(interactive=False)
        )
    
    try:
        # Load config
        config = load_config(PROJECT_ROOT)
        
        # Initialize SessionManager
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state
        )
        
        # Load ResearchBrief
        progress(0.1, desc="リサーチ結果を読み込み中...")
        research_brief = session_manager.load_research_brief()
        
        progress_text = f"セッションID: {session_manager.session_id}\n"
        progress_text += "台本生成を開始します...\n"
        
        # Progress callback
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, description: str):
            progress(ratio, desc=description)
        
        callbacks = ProgressCallback(
            log_callback=log_callback,
            progress_callback=progress_callback
        )
        
        # Execute scripting phase
        progress(0.2, desc="台本生成中...")
        script_artifact = await execute_scripting_phase(
            research_brief=research_brief,
            session_manager=session_manager,
            config=config,
            avoid_topics=avoid_topics.strip() if avoid_topics else None,
            provider=provider,
            callbacks=callbacks
        )
        
        progress(0.9, desc="エディタ準備中...")
        
        # Convert Script to DataFrame format
        turns_data = script_to_dataframe(script_artifact.script)
        
        # Convert Script to JSON
        json_data = script_artifact.script.model_dump_json(indent=2)
        
        # Extract metadata
        title = script_artifact.script.title
        thumbnail_title = script_artifact.script.thumbnail_title
        description = script_artifact.script.description
        
        progress_text += "\n".join(log_messages[-10:])
        progress_text += f"\n\n✅ 台本生成完了！"
        
        progress(1.0, desc="完了!")
        
        return (
            progress_text,
            gr.update(visible=True),
            turns_data,
            json_data,
            title,
            thumbnail_title,
            description,
            gr.update(interactive=True)
        )
        
    except Exception as e:
        import traceback
        error_msg = f"❌ 台本生成中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
        return (
            error_msg,
            gr.update(visible=False),
            [], "", "", "", "", gr.update(interactive=False)
        )


def script_to_dataframe(script: Script) -> List[List]:
    """Convert Script to DataFrame format
    
    Args:
        script: Script object
        
    Returns:
        List of rows for DataFrame (only dialogue turns)
    """
    rows = []
    for i, turn in enumerate(script.sections, 1):
        # Only include dialogue turns in the editable table
        if turn.is_dialogue() and turn.speaker and turn.text:
            rows.append([
                i,
                turn.speaker,
                turn.text,
                turn.emotion or ""
            ])
    return rows


def dataframe_to_script(
    turns_data: List[List],
    title: str,
    thumbnail_title: str,
    description: str
) -> Script:
    """Convert DataFrame to Script object with robust validation
    
    Args:
        turns_data: DataFrame data
        title: Script title
        thumbnail_title: Thumbnail title
        description: Script description
        
    Returns:
        Script object
    """
    sections = []
    for row in turns_data:
        # Robust validation: ensure row has at least 3 columns and text is not empty
        if len(row) >= 3:
            speaker = str(row[1]).strip() if row[1] else "A"
            text = str(row[2]).strip() if row[2] else ""
            
            # Skip empty text rows
            if not text:
                continue
            
            # Validate speaker is A or B
            if speaker not in ["A", "B"]:
                speaker = "A"
            
            # Extract emotion (optional)
            emotion = str(row[3]).strip() if len(row) > 3 and row[3] else None
            if emotion == "":
                emotion = None
            
            sections.append(DialogueTurn(
                speaker=speaker,
                text=text,
                emotion=emotion
            ))
    
    return Script(
        title=title,
        thumbnail_title=thumbnail_title,
        description=description,
        sections=sections
    )


def hitl_save_script_edits(
    session_state: str,
    turns_data: List[List],
    title: str,
    thumbnail_title: str,
    description: str
) -> str:
    """Save script edits to RadioScriptArtifact
    
    Args:
        session_state: Current session ID
        turns_data: Edited DataFrame data
        title: Script title
        thumbnail_title: Thumbnail title
        description: Script description
        
    Returns:
        Status message
    """
    if not session_state:
        return "❌ エラー: セッションが見つかりません。"
    
    try:
        # Initialize SessionManager
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state
        )
        
        # Load existing RadioScriptArtifact
        script_artifact = session_manager.load_script_artifact()
        
        # Convert DataFrame to Script
        updated_script = dataframe_to_script(turns_data, title, thumbnail_title, description)
        
        # Update RadioScriptArtifact
        script_artifact.script = updated_script
        
        # Save
        session_manager.save_script_artifact(script_artifact)
        
        return f"✅ 編集内容を保存しました ({datetime.now().strftime('%H:%M:%S')})"
        
    except Exception as e:
        import traceback
        return f"❌ 保存中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"


def hitl_approve_script(
    session_state: str
) -> Tuple[gr.update, str]:
    """Approve script and open Gate 3
    
    Args:
        session_state: Current session ID
        
    Returns:
        Tuple of (gate3_accordion_update, status_message)
    """
    if not session_state:
        return gr.update(open=False), "❌ エラー: セッションが見つかりません。"
    
    return gr.update(open=True), f"✅ Gate 3を開放しました。動画生成を開始できます。"


async def hitl_execute_production(
    session_state: str,
    bg_filename: str,
    bgm_filename: str,
    speed_scale: float,
    bgm_volume: float,
    progress=gr.Progress()
) -> Tuple[str, gr.update, str, str, str, str, str]:
    """Execute production phase and display output
    
    Args:
        session_state: Current session ID
        bg_filename: Background image filename
        bgm_filename: BGM filename
        speed_scale: Audio speed scale
        bgm_volume: BGM volume
        progress: Gradio progress bar
        
    Returns:
        Tuple of (progress_text, output_section_update, video_path, video_file, audio_path, subtitle_path, metadata)
    """
    if not session_state:
        return (
            "❌ エラー: セッションが見つかりません。",
            gr.update(visible=False),
            None, None, None, None, ""
        )
    
    try:
        # Load config
        config = load_config(PROJECT_ROOT)
        
        # Initialize SessionManager
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state
        )
        
        # Load RadioScriptArtifact
        progress(0.1, desc="台本を読み込み中...")
        script_artifact = session_manager.load_script_artifact()
        
        progress_text = f"セッションID: {session_manager.session_id}\n"
        progress_text += "動画生成を開始します...\n"
        
        # Progress callback
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, description: str):
            progress(ratio, desc=description)
        
        callbacks = ProgressCallback(
            log_callback=log_callback,
            progress_callback=progress_callback
        )
        
        # Execute production phase
        progress(0.2, desc="動画生成中...")
        result = await execute_production_phase(
            script_artifact=script_artifact,
            session_manager=session_manager,
            config=config,
            project_root=PROJECT_ROOT,
            speed_scale=speed_scale,
            callbacks=callbacks
        )
        
        progress(0.95, desc="メタデータ生成中...")
        
        # Format metadata
        metadata = f"""タイトル: {script_artifact.script.title}

概要:
{script_artifact.script.description}

動画情報:
- 長さ: {result.duration_sec:.1f}秒
- サイズ: {result.file_size_mb:.1f}MB
"""
        
        progress_text += "\n".join(log_messages[-10:])
        progress_text += f"\n\n✅ 動画生成完了！"
        
        progress(1.0, desc="完了!")
        
        return (
            progress_text,
            gr.update(visible=True),
            str(result.video_path),
            str(result.video_path),
            str(result.audio_path),
            str(result.subtitle_path),
            metadata
        )
        
    except Exception as e:
        import traceback
        error_msg = f"❌ 動画生成中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
        return (
            error_msg,
            gr.update(visible=False),
            None, None, None, None, ""
        )


async def hitl_regenerate_script(
    session_state: str,
    provider: str,
    avoid_topics: str,
    progress=gr.Progress()
) -> Tuple[str, gr.update, List, str, str, str, str, gr.update]:
    """Regenerate script with same research data but potentially different parameters
    
    Args:
        session_state: Current session ID
        provider: LLM provider
        avoid_topics: Topics to avoid
        progress: Gradio progress bar
        
    Returns:
        Tuple of (progress_text, editor_section_update, turns_data, json_data, title, thumbnail_title, description, approve_btn_update)
    """
    if not session_state:
        return (
            "❌ エラー: セッションが見つかりません。まずリサーチを実行してください。",
            gr.update(visible=False),
            [], "", "", "", "", gr.update(interactive=False)
        )
    
    try:
        # Load config
        config = load_config(PROJECT_ROOT)
        
        # Initialize SessionManager
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state
        )
        
        # Load ResearchBrief
        progress(0.1, desc="リサーチ結果を読み込み中...")
        research_brief = session_manager.load_research_brief()
        
        progress_text = f"セッションID: {session_manager.session_id}\n"
        progress_text += "台本を再生成します...\n"
        
        # Progress callback
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, description: str):
            progress(ratio, desc=description)
        
        callbacks = ProgressCallback(
            log_callback=log_callback,
            progress_callback=progress_callback
        )
        
        # Execute scripting phase with regeneration
        progress(0.2, desc="台本を再生成中...")
        script_artifact = await execute_scripting_phase(
            research_brief=research_brief,
            session_manager=session_manager,
            config=config,
            avoid_topics=avoid_topics.strip() if avoid_topics else None,
            provider=provider,
            callbacks=callbacks
        )
        
        progress(0.9, desc="エディタ準備中...")
        
        # Convert Script to DataFrame format
        turns_data = script_to_dataframe(script_artifact.script)
        
        # Convert Script to JSON
        json_data = script_artifact.script.model_dump_json(indent=2)
        
        # Extract metadata
        title = script_artifact.script.title
        thumbnail_title = script_artifact.script.thumbnail_title
        description = script_artifact.script.description
        
        progress_text += "\n".join(log_messages[-10:])
        progress_text += f"\n\n✅ 台本再生成完了！"
        
        progress(1.0, desc="完了!")
        
        return (
            progress_text,
            gr.update(visible=True),
            turns_data,
            json_data,
            title,
            thumbnail_title,
            description,
            gr.update(interactive=True)
        )
        
    except Exception as e:
        import traceback
        error_msg = f"❌ 台本再生成中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
        return (
            error_msg,
            gr.update(visible=False),
            [], "", "", "", "", gr.update(interactive=False)
        )
