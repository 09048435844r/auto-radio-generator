"""HITL UI Event Handlers

HITLモードのイベントハンドラとバックエンド連動ロジック
"""
import gradio as gr
import logging
from pathlib import Path
from typing import Optional, Tuple, List
from datetime import datetime

# Setup logger
logger = logging.getLogger(__name__)

from core.session_manager import SessionManager
from core.models.artifacts import ResearchBrief
from core.models.script import RadioScriptArtifact, Script, DialogueTurn
from core.models.curation import CurationResult, CuratedTopic
from core.models import load_config
from services.pipeline import (
    execute_research_phase,
    execute_curation_only,
    execute_scripting_phase,
    execute_production_phase,
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
        # Log detailed error to server logs
        logger.error(f"Research execution failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return concise error message to UI
        error_msg = f"❌ リサーチ中にエラーが発生しました: {str(e)}"
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


# ----------------------------------------------------------------------
# Gate 2a: Topic Curation handlers (Phase 2 HITL 施策⑤)
# ----------------------------------------------------------------------

def _curation_to_dataframe(curation: CurationResult) -> List[List]:
    """Convert CurationResult to Dataframe rows (editable columns only).

    Columns: [#, タイトル, 選定理由, トーン, 推定ターン, 優先度]
    """
    rows: List[List] = []
    for i, t in enumerate(curation.topics, 1):
        rows.append([
            i,
            t.title or "",
            getattr(t, "selection_reason", "") or "",
            t.tone or "",
            int(t.estimated_turns or 30),
            int(t.priority or i),
        ])
    return rows


def _dataframe_to_curation(
    topics_df,
    original: Optional[CurationResult],
) -> CurationResult:
    """Merge Dataframe edits back into CurationResult.

    Preserves `content` and `key_facts` from the original (not in Dataframe),
    while applying edits from UI for title/selection_reason/tone/turns/priority.

    Defensive: accepts List[List] or pandas.DataFrame.
    """
    # Normalize to list-of-lists
    try:
        import pandas as pd  # noqa: F401
        if hasattr(topics_df, "values") and hasattr(topics_df, "columns"):
            topics_df = topics_df.values.tolist()
    except ImportError:
        pass

    original_topics = (original.topics if original else []) or []
    new_topics: List[CuratedTopic] = []
    for idx, row in enumerate(topics_df or []):
        if not row or len(row) < 2:
            continue
        title = str(row[1]).strip() if row[1] is not None else ""
        if not title:
            # Skip empty rows (user may have removed a topic)
            continue
        selection_reason = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""
        tone = str(row[3]).strip() if len(row) > 3 and row[3] is not None else "解説"
        try:
            estimated_turns = int(row[4]) if len(row) > 4 and row[4] not in (None, "") else 30
        except (TypeError, ValueError):
            estimated_turns = 30
        try:
            priority = int(row[5]) if len(row) > 5 and row[5] not in (None, "") else (idx + 1)
        except (TypeError, ValueError):
            priority = idx + 1

        # Preserve content / key_facts from original if available at same index
        base = original_topics[idx] if idx < len(original_topics) else None
        content = base.content if base else ""
        key_facts = list(base.key_facts) if base and base.key_facts else []

        new_topics.append(CuratedTopic(
            title=title,
            content=content,
            priority=priority,
            estimated_turns=estimated_turns,
            tone=tone or "解説",
            key_facts=key_facts,
            selection_reason=selection_reason,
        ))

    # Sort by priority (ascending) to keep downstream ordering consistent
    new_topics.sort(key=lambda t: t.priority)

    return CurationResult(
        topics=new_topics,
        curator_reasoning=(original.curator_reasoning if original else "") or "",
    )


async def hitl_execute_curation(
    session_state: str,
    provider: str,
    progress=gr.Progress(),
) -> Tuple[str, List, str]:
    """Gate 2a: Run Curator only and return topics for human editing.

    Returns:
        (progress_text, topics_df_rows, curation_json_text)
    """
    if not session_state:
        return (
            "❌ エラー: セッションが見つかりません。先にリサーチを完了してください。",
            [],
            "",
        )

    try:
        config = load_config(PROJECT_ROOT)
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state,
        )

        # Need a ResearchBrief to run Curator
        if not session_manager.has_research_brief():
            return (
                "❌ エラー: このセッションに research_brief.json がありません。",
                [],
                "",
            )
        research_brief = session_manager.load_research_brief()

        progress(0.1, desc="Curator 起動中...")

        log_messages: List[str] = []

        def log_cb(msg: str):
            log_messages.append(msg)

        def prog_cb(ratio: float, description: str):
            progress(ratio, desc=description)

        callbacks = ProgressCallback(log_callback=log_cb, progress_callback=prog_cb)

        curation_result = await execute_curation_only(
            research_brief=research_brief,
            session_manager=session_manager,
            config=config,
            provider=provider,
            callbacks=callbacks,
        )

        progress(0.95, desc="エディタ準備中...")
        topics_df = _curation_to_dataframe(curation_result)
        curation_json = curation_result.model_dump_json(indent=2)

        progress_text = f"セッションID: {session_manager.session_id}\n"
        progress_text += "\n".join(log_messages[-10:])
        progress_text += f"\n\n✅ Curator 完了: {len(curation_result.topics)} トピック選定"

        progress(1.0, desc="完了!")
        return progress_text, topics_df, curation_json

    except Exception as e:
        import traceback
        logger.error(f"Curation execution failed: {e}")
        logger.error(traceback.format_exc())
        return (
            f"❌ Curator 実行中にエラーが発生しました: {e}",
            [],
            "",
        )


def _show_curation_editor(
    progress_text: str,
    topics_df: List,
    curation_json: str,
) -> gr.update:
    """Show curation editor section after data is populated.

    Called via .then() to avoid the Gradio visibility + child-value loss bug
    (same pattern as _show_research_preview).
    """
    # Show only on success (non-error progress text AND non-empty topics).
    # Note: topics_df may be a pandas.DataFrame at runtime (despite the List hint),
    # so we MUST avoid implicit boolean coercion. Use explicit length check, which
    # works uniformly for list, tuple, and DataFrame.
    has_topics = topics_df is not None
    if has_topics:
        try:
            has_topics = len(topics_df) > 0
        except TypeError:
            has_topics = False
    if progress_text and "❌" not in progress_text and has_topics:
        return gr.update(visible=True)
    return gr.update(visible=False)


def hitl_save_curation_edits(
    session_state: str,
    topics_df,
    curation_json: str,
) -> str:
    """Save edited CurationResult back to session.

    Priority: If `curation_json` has been edited and is valid JSON, use it as the
    source of truth (advanced editor takes precedence). Otherwise rebuild from
    the Dataframe edits while preserving content/key_facts from the saved file.
    """
    if not session_state:
        return "❌ エラー: セッションが見つかりません。"

    try:
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state,
        )

        # Load the on-disk curation (if any) for preservation of non-editable fields
        existing: Optional[CurationResult] = None
        if session_manager.has_curation_result():
            try:
                existing = session_manager.load_curation_result()
            except Exception as e:
                logger.warning(f"Could not load existing curation_result.json: {e}")

        merged: Optional[CurationResult] = None

        # Attempt 1: JSON editor takes priority if user edited it
        if curation_json and curation_json.strip():
            try:
                merged = CurationResult.model_validate_json(curation_json)
            except Exception as e:
                logger.info(
                    f"JSON editor content invalid, falling back to Dataframe merge: {e}"
                )

        # Attempt 2: Build from Dataframe (merge with existing to preserve content)
        if merged is None:
            merged = _dataframe_to_curation(topics_df, existing)

        if not merged.topics:
            return "❌ エラー: 保存するトピックがありません。"

        session_manager.save_curation_result(merged)
        return (
            f"✅ 編集内容を保存しました ({datetime.now().strftime('%H:%M:%S')}) - "
            f"{len(merged.topics)} トピック"
        )

    except Exception as e:
        import traceback
        logger.error(f"Curation save failed: {e}")
        logger.error(traceback.format_exc())
        return f"❌ 保存中にエラーが発生しました: {e}"


def hitl_approve_curation(session_state: str) -> Tuple[gr.update, str]:
    """Approve edited curation and open Gate 2.

    Returns:
        (gate2_accordion_update, status_message)
    """
    if not session_state:
        return gr.update(open=False), "❌ エラー: セッションが見つかりません。"

    try:
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=session_state,
        )
        if not session_manager.has_curation_result():
            return gr.update(open=False), (
                "❌ エラー: 先にトピック選定（および保存）を完了してください。"
            )
    except Exception as e:
        return gr.update(open=False), f"❌ セッション確認エラー: {e}"

    return gr.update(open=True), (
        "✅ Gate 2 を開放しました。Curator はスキップされ、編集済みトピックで台本が生成されます。"
    )


def hitl_approve_research(
    session_state: str
) -> Tuple[gr.update, gr.update, str]:
    """Approve research and open Gate 2a (Topic Curation, optional) + Gate 2 (Script).

    Both accordions are opened so users can either edit topics via Gate 2a
    or skip straight to Gate 2 for the traditional flow.

    Args:
        session_state: Current session ID

    Returns:
        Tuple of (gate2a_accordion_update, gate2_accordion_update, status_message)
    """
    print(f"[DEBUG] hitl_approve_research called with session_state: '{session_state}'")

    if not session_state:
        print("[DEBUG] session_state is empty, returning error")
        return gr.update(open=False), gr.update(open=False), "❌ エラー: セッションが見つかりません。"

    print(f"[DEBUG] Opening Gate 2a + Gate 2 for session: {session_state}")
    return (
        gr.update(open=True),
        gr.update(open=True),
        "✅ Gate 2a（トピック選定・オプショナル）/ Gate 2（台本生成）を開放しました。",
    )


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
        # Log detailed error to server logs
        logger.error(f"Research import failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return concise error message to UI
        error_msg = f"❌ インポート中にエラーが発生しました: {str(e)}"
        return (
            "", error_msg,
            "", "", "", [], ""
        )


async def hitl_import_script(
    filepath: str | None,
    progress=gr.Progress()
) -> Tuple[str, str, List, str, str, str, str]:
    """Import existing script data and display in editor
    
    Args:
        filepath: Path to script.json file
        progress: Gradio progress bar
        
    Returns:
        Tuple of (session_id, progress_text, turns_data, json_data, title, thumbnail_title, description)
    """
    if not filepath:
        return (
            "", "❌ エラー: ファイルを選択してください。",
            [], "", "", "", ""
        )
    
    try:
        import json
        from pathlib import Path
        from core.models.script import Script, RadioScriptArtifact
        from core.session_manager import SessionManager
        
        progress(0.1, desc="台本データを読み込み中...")
        
        # Load script from file
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check if this is a script_artifact.json (contains session_id, segments, visual_identity)
        is_artifact = 'session_id' in data and 'script' in data
        
        if is_artifact:
            # Import complete RadioScriptArtifact (preserves segments and visual_identity)
            logger.info("✓ Detected script_artifact.json - importing with segments and visual_identity")
            script = Script(**data['script'])
            imported_segments = data.get('segments')
            imported_visual_identity = data.get('visual_identity')
            logger.info(f"  - Segments: {len(imported_segments) if imported_segments else 0} segments")
            logger.info(f"  - Visual identity: {'present' if imported_visual_identity else 'missing'}")
        else:
            # Import plain script.json
            logger.info("✓ Detected script.json - importing script only (no segments)")
            script = Script(**data)
            imported_segments = None
            imported_visual_identity = None
        
        # Create new session for imported data
        session_manager = SessionManager(
            project_root=PROJECT_ROOT,
            session_id=None  # Create new session
        )
        
        # Save imported script to new session
        script_path = session_manager.session_dir / "script.json"
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script.model_dump(), f, ensure_ascii=False, indent=2)
        
        # Also create script_artifact.json with visual identity and segments
        # This allows production phase to work immediately after import
        from core.models.visual import (
            VisualIdentity,
            DEFAULT_PRIMARY_COLOR,
            DEFAULT_SECONDARY_COLOR,
            DEFAULT_COLOR_MOOD,
            DEFAULT_AESTHETIC,
            DEFAULT_VISUAL_KEYWORDS
        )
        
        # Use imported visual_identity if available, otherwise create default
        if imported_visual_identity:
            visual_identity_dict = imported_visual_identity
        else:
            visual_identity = VisualIdentity(
                primary_color=DEFAULT_PRIMARY_COLOR,
                secondary_color=DEFAULT_SECONDARY_COLOR,
                color_mood=DEFAULT_COLOR_MOOD,
                aesthetic=DEFAULT_AESTHETIC,
                visual_keywords=list(DEFAULT_VISUAL_KEYWORDS)  # Convert tuple to list
            )
            visual_identity_dict = visual_identity.model_dump()
        
        script_artifact = RadioScriptArtifact(
            session_id=session_manager.session_id,
            script=script,
            segments=imported_segments,  # Preserve segments if available
            visual_identity=visual_identity_dict
        )
        
        session_manager.save_script_artifact(script_artifact)
        
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
            turns_data,  # hitl_script_turns_editor
            json_data,  # hitl_script_json_editor
            title,  # hitl_script_title
            thumbnail_title,  # hitl_script_thumbnail_title
            description,  # hitl_script_description
        )
        
    except Exception as e:
        import traceback
        # Log detailed error to server logs
        logger.error(f"Script import failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return concise error message to UI
        error_msg = f"❌ インポート中にエラーが発生しました: {str(e)}"
        return (
            "", error_msg,
            [], "", "", "", ""
        )


async def hitl_execute_scripting(
    session_state: str,
    provider: str,
    avoid_topics: str,
    progress=gr.Progress()
) -> Tuple[str, List, str, str, str, str]:
    """Execute scripting phase and return data (Step 1 of Two-step pattern)
    
    NOTE: Column visibility and Button interactivity are handled by a
    separate .then() handler (_show_script_editor) to avoid a Gradio bug
    where toggling Column visibility in the same return tuple as child
    component values causes child values to be lost.
    
    Args:
        session_state: Current session ID
        provider: LLM provider
        avoid_topics: Topics to avoid
        progress: Gradio progress bar
        
    Returns:
        Tuple of (progress_text, turns_data, json_data, title, thumbnail_title, description)
    """
    if not session_state:
        return (
            "❌ エラー: セッションが見つかりません。まずリサーチを実行してください。",
            [], "", "", "", ""
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
        # Note: Internal progress updates go to log only (not Gradio progress bar).
        # Sending fine-grained progress(ratio) from within execute_scripting_phase
        # causes Gradio's progress overlay to persist over output components.
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, description: str):
            log_messages.append(f"[{ratio*100:.0f}%] {description}")
        
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
        
        logger.info(f"hitl_execute_scripting: Script generated with {len(script_artifact.script.sections)} sections")
        
        progress(0.9, desc="エディタ準備中...")
        
        # Convert Script to DataFrame format
        turns_data = script_to_dataframe(script_artifact.script)
        logger.info(f"hitl_execute_scripting: Converted to {len(turns_data)} DataFrame rows")
        
        # Convert Script to JSON
        json_data = script_artifact.script.model_dump_json(indent=2)
        
        # Extract metadata
        title = script_artifact.script.title
        thumbnail_title = script_artifact.script.thumbnail_title
        description = script_artifact.script.description
        
        # Debug: Log turns_data details
        logger.info(f"hitl_execute_scripting: Returning {len(turns_data)} dialogue turns")
        logger.info(f"hitl_execute_scripting: turns_data type={type(turns_data).__name__}")
        if len(turns_data) > 0:
            logger.info(f"hitl_execute_scripting: First row sample: {turns_data[0]}")
        
        progress_text += "\n".join(log_messages[-10:])
        progress_text += f"\n\n✅ 台本生成完了！"
        progress_text += f"\n📊 DEBUG: 生成された対話ターン数: {len(turns_data)}行"
        progress_text += f"\n📊 DEBUG: 返却データ型: {type(turns_data).__name__}"
        
        progress(1.0, desc="完了!")
        
        return (
            progress_text,  # hitl_script_progress
            turns_data,     # hitl_script_turns_editor (raw list)
            json_data,      # hitl_script_json_editor
            title,          # hitl_script_title
            thumbnail_title,  # hitl_script_thumbnail_title
            description     # hitl_script_description
        )
        
    except Exception as e:
        import traceback
        # Log detailed error to server logs
        error_trace = traceback.format_exc()
        logger.error(f"Script generation failed: {str(e)}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Full traceback:\n{error_trace}")
        
        # Return detailed error message to UI for debugging
        error_msg = f"❌ 台本生成中にエラーが発生しました\n"
        error_msg += f"エラー種別: {type(e).__name__}\n"
        error_msg += f"エラー内容: {str(e)}\n"
        error_msg += f"詳細はターミナルログを確認してください"
        
        return (
            error_msg,  # hitl_script_progress
            [],         # hitl_script_turns_editor (empty list)
            "",         # hitl_script_json_editor
            "",         # hitl_script_title
            "",         # hitl_script_thumbnail_title
            ""          # hitl_script_description
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
    
    # Debug: Log what we received from Gradio
    logger.debug(f"hitl_save_script_edits: Received turns_data type={type(turns_data).__name__}")
    
    # Handle pandas DataFrame (Gradio may pass DataFrame instead of List[List])
    try:
        import pandas as pd
        if isinstance(turns_data, pd.DataFrame):
            logger.debug(f"hitl_save_script_edits: Received DataFrame with {len(turns_data)} rows")
            logger.debug(f"hitl_save_script_edits: DataFrame columns: {turns_data.columns.tolist()}")
            if len(turns_data) > 0:
                logger.debug(f"hitl_save_script_edits: First row: {turns_data.iloc[0].tolist()}")
                logger.debug(f"hitl_save_script_edits: Last row: {turns_data.iloc[-1].tolist()}")
            # Convert DataFrame to List[List]
            turns_data = turns_data.values.tolist()
            logger.debug(f"hitl_save_script_edits: Converted to list with {len(turns_data)} rows")
        else:
            logger.debug(f"hitl_save_script_edits: Received {len(turns_data) if turns_data else 0} rows")
            if turns_data and len(turns_data) > 0:
                logger.debug(f"hitl_save_script_edits: First row: {turns_data[0]}")
                logger.debug(f"hitl_save_script_edits: Last row: {turns_data[-1]}")
    except ImportError:
        # pandas not installed, assume turns_data is already List[List]
        logger.debug(f"hitl_save_script_edits: pandas not available, assuming List[List] format")
        if turns_data and len(turns_data) > 0:
            logger.debug(f"hitl_save_script_edits: Received {len(turns_data)} rows")
    
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
        # Log detailed error to server logs
        logger.error(f"Script save failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return concise error message to UI
        return f"❌ 保存中にエラーが発生しました: {str(e)}"


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
) -> Tuple[str, str, str, str, str, str]:
    """Execute production phase and return data (Step 1 of Two-step pattern)
    
    NOTE: Column visibility is handled by a separate .then() handler
    (_show_production_output) to avoid a Gradio bug.
    
    Args:
        session_state: Current session ID
        bg_filename: Background image filename
        bgm_filename: BGM filename
        speed_scale: Audio speed scale
        bgm_volume: BGM volume
        progress: Gradio progress bar
        
    Returns:
        Tuple of (progress_text, video_path, video_file, audio_path, subtitle_path, metadata)
    """
    if not session_state:
        return (
            "❌ エラー: セッションが見つかりません。",
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
            progress_text,          # hitl_production_progress
            str(result.video_path), # hitl_production_video_path
            str(result.video_path), # hitl_production_video_file
            str(result.audio_path), # hitl_production_audio_path
            str(result.subtitle_path),  # hitl_production_subtitle_path
            metadata                # hitl_production_metadata
        )
        
    except Exception as e:
        import traceback
        # Log detailed error to server logs
        logger.error(f"Production phase failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return concise error message to UI
        error_msg = f"❌ 動画生成中にエラーが発生しました: {str(e)}"
        return (
            error_msg,  # hitl_production_progress
            None,       # hitl_production_video_path
            None,       # hitl_production_video_file
            None,       # hitl_production_audio_path
            None,       # hitl_production_subtitle_path
            ""          # hitl_production_metadata
        )


async def hitl_regenerate_script(
    session_state: str,
    provider: str,
    avoid_topics: str,
    progress=gr.Progress()
) -> Tuple[str, List, str, str, str, str]:
    """Regenerate script with same research data (Step 1 of Two-step pattern)
    
    NOTE: Column visibility and Button interactivity are handled by a
    separate .then() handler (_show_script_editor) to avoid a Gradio bug.
    
    Args:
        session_state: Current session ID
        provider: LLM provider
        avoid_topics: Topics to avoid
        progress: Gradio progress bar
        
    Returns:
        Tuple of (progress_text, turns_data, json_data, title, thumbnail_title, description)
    """
    if not session_state:
        return (
            "❌ エラー: セッションが見つかりません。まずリサーチを実行してください。",
            [], "", "", "", ""
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
        
        # Progress callback (log only, not Gradio progress bar)
        log_messages = []
        
        def log_callback(msg: str):
            log_messages.append(msg)
        
        def progress_callback(ratio: float, description: str):
            log_messages.append(f"[{ratio*100:.0f}%] {description}")
        
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
        
        # Debug: Log turns_data details
        logger.info(f"hitl_regenerate_script: Returning {len(turns_data)} dialogue turns")
        logger.info(f"hitl_regenerate_script: turns_data type={type(turns_data).__name__}")
        if len(turns_data) > 0:
            logger.info(f"hitl_regenerate_script: First row sample: {turns_data[0]}")
        
        progress_text += "\n".join(log_messages[-10:])
        progress_text += f"\n\n✅ 台本再生成完了！"
        
        progress(1.0, desc="完了!")
        
        return (
            progress_text,  # hitl_script_progress
            turns_data,     # hitl_script_turns_editor (raw list)
            json_data,      # hitl_script_json_editor
            title,          # hitl_script_title
            thumbnail_title,  # hitl_script_thumbnail_title
            description     # hitl_script_description
        )
        
    except Exception as e:
        import traceback
        # Log detailed error to server logs
        logger.error(f"Script regeneration failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return concise error message to UI
        error_msg = f"❌ 台本再生成中にエラーが発生しました: {str(e)}"
        return (
            error_msg,  # hitl_script_progress
            [],         # hitl_script_turns_editor (empty list)
            "",         # hitl_script_json_editor
            "",         # hitl_script_title
            "",         # hitl_script_thumbnail_title
            ""          # hitl_script_description
        )


def _show_script_editor(
    progress_text: str,
    turns_data: List,
    title: str,
) -> Tuple[gr.update, gr.update]:
    """Show script editor section after data is populated (Step 2 of Two-step pattern)

    This is called via .then() AFTER scripting/import/regeneration handler
    completes, to avoid Gradio bug where toggling parent Column visibility
    together with child component values in a single return loses child values.

    Returns:
        Tuple of (editor_section_visibility, approve_btn_interactivity)
    """
    has_error = (not progress_text) or ("❌" in progress_text)
    try:
        has_turns = len(turns_data) > 0
    except (TypeError, ValueError):
        has_turns = False
    has_title = bool(title and title.strip())

    logger.info(
        f"_show_script_editor: has_error={has_error}, "
        f"has_turns={has_turns} (type={type(turns_data).__name__}), "
        f"has_title={has_title} (title={title!r})"
    )

    if (not has_error) and has_turns and has_title:
        return gr.update(visible=True), gr.update(interactive=True)
    return gr.update(visible=False), gr.update(interactive=False)


def _show_production_output(
    progress_text: str,
    video_path: str,
) -> gr.update:
    """Show production output section after video generation (Step 2 of Two-step pattern)
    
    This is called via .then() AFTER hitl_execute_production completes,
    to avoid Gradio bug where toggling Column visibility together with
    child component values in a single return loses child values.
    
    Returns:
        gr.update for output_section visibility
    """
    has_error = (not progress_text) or ("❌" in progress_text)
    has_video = bool(video_path and video_path != "None")
    
    logger.info(
        f"_show_production_output: has_error={has_error}, "
        f"has_video={has_video} (video_path={video_path!r})"
    )
    
    if (not has_error) and has_video:
        return gr.update(visible=True)
    return gr.update(visible=False)
