"""台本作成フェーズ実行サービス

ResearchBriefを入力として台本を生成し、RadioScriptArtifactを生成する。
"""
import asyncio
import time
from typing import Optional
from dataclasses import asdict

from core.models import AppConfig
from core.models.artifacts import ResearchBrief
from core.models.script import RadioScriptArtifact
from core.models.execution_context import ExecutionContext
from core.session_manager import SessionManager
from core.interfaces import ResearchResult
from workflow import (
    ProgressCallback,
    create_script_generator,
    _build_speaker_diagnostics,
    _swap_script_speakers,
    _to_json_safe
)


async def execute_curation_only(
    research_brief: ResearchBrief,
    session_manager: SessionManager,
    config: AppConfig,
    provider: str = "gemini",
    callbacks: Optional[ProgressCallback] = None,
):
    """Curator 単独実行: リサーチ結果からトピックを選定し CurationResult を session に保存する

    HITL (Gate 2a) で使用する。ユーザーが編集する前の生の Curator 出力を取得する。

    Args:
        research_brief: ResearchBrief from research phase
        session_manager: SessionManager instance (saves curation_result.json)
        config: Application config
        provider: LLM provider
        callbacks: Progress callback

    Returns:
        CurationResult: トピック選定結果（session にも保存済み）
    """
    from services.script_generation.topic_curator import TopicCurator
    from core.models.research import ResearchSource

    cb = callbacks or ProgressCallback()

    # Build ExecutionContext just to get the LLM port wiring (same as scripting_phase)
    context = ExecutionContext(
        provider=provider,
        config=config,
        log_callback=cb.log if cb else None,
        progress_callback=cb.progress if cb else None,
        use_orchestrator=True,
        enable_research=True,
        session_dir=session_manager.session_dir,
    )

    # Convert ResearchBrief to ResearchResult for the curator
    research_sources = [
        ResearchSource.model_validate(source_dict)
        for source_dict in research_brief.research_sources
    ]
    research_data = ResearchResult(
        topic=research_brief.theme,
        mode=research_brief.research_mode,
        content=research_brief.research_content,
        sources=research_sources,
        usage=None,
    )

    cb.log(f"\n== Curation Only Phase: TopicCurator ==")
    cb.log(f"Theme: {research_brief.theme}")
    cb.log(f"Provider: {provider}")
    cb.progress(0.10, "🔍 トピック選定中...")

    # Create curator using the curator-specific LLM port from ExecutionContext
    llm_port = context.create_llm_port(role="curator") if hasattr(context, "create_llm_port") else context.create_llm_port()
    curator = TopicCurator(llm_port, config)

    curation_result = await curator.curate_topics(
        research_data=research_data,
        progress_log=cb.log,
    )

    # Persist to session
    saved_path = session_manager.save_curation_result(curation_result)
    cb.log(f"✓ CurationResult saved: {saved_path}")
    cb.progress(1.0, "✅ トピック選定完了")

    return curation_result


async def execute_scripting_phase(
    research_brief: ResearchBrief,
    session_manager: SessionManager,
    config: AppConfig,
    excluded_topics: Optional[str] = None,
    avoid_topics: Optional[str] = None,
    provider: str = "gemini",
    callbacks: Optional[ProgressCallback] = None,
    preset_curation=None,
) -> RadioScriptArtifact:
    """Execute scripting phase and generate RadioScriptArtifact
    
    Args:
        research_brief: ResearchBrief from research phase
        session_manager: SessionManager instance
        config: Application config
        excluded_topics: Topics to exclude (for multi-part scripts)
        avoid_topics: Topics to avoid (Negative Prompt, optional)
        provider: LLM provider ("gemini" | "openai" | "anthropic" | "ollama")
        callbacks: Progress callback
        preset_curation: Optional CurationResult from HITL (human-edited topics).
                         If provided, skip Curator invocation inside orchestrator.
                         If None and session has curation_result.json, it will be loaded automatically.
        
    Returns:
        RadioScriptArtifact: Scripting phase output artifact
    """
    cb = callbacks or ProgressCallback()
    
    # Create ExecutionContext for provider-agnostic workflow
    context = ExecutionContext(
        provider=provider,
        config=config,
        log_callback=cb.log if cb else None,
        progress_callback=cb.progress if cb else None,
        use_orchestrator=config.yaml.script_generator.orchestrator.enabled,
        enable_research=True,
        session_dir=session_manager.session_dir  # For markdown script saving
    )
    
    # Convert ResearchBrief to ResearchResult (for backward compatibility)
    from core.models.research import ResearchSource
    
    research_sources = [
        ResearchSource.model_validate(source_dict) 
        for source_dict in research_brief.research_sources
    ]
    
    research_data = ResearchResult(
        topic=research_brief.theme,
        mode=research_brief.research_mode,
        content=research_brief.research_content,
        sources=research_sources,
        usage=None  # Usage already tracked in ResearchBrief
    )
    
    # Step 1: Script generation
    cb.log(f"\n== Scripting Phase: Script Generation ==")
    cb.log(f"Theme: {research_brief.theme}")
    cb.log(f"Provider: {context.provider}")
    
    cb.log(f"Engine: {'ScriptOrchestrator (Agentic)' if context.use_orchestrator else 'Direct LLM'}")
    cb.progress(0.50, f"📝 Generating script ({'Orchestrator' if context.use_orchestrator else 'Direct'} - {context.provider})...")
    
    script_start = time.time()
    segments = None
    
    if context.use_orchestrator and research_data is not None:
        # Hierarchical Agentic Workflow with ExecutionContext
        from services.script_generation.orchestrator import ScriptOrchestrator

        # HITL Gate 2a support: auto-load curation_result.json if present and not explicitly passed
        effective_preset = preset_curation
        if effective_preset is None and session_manager.has_curation_result():
            try:
                effective_preset = session_manager.load_curation_result()
                cb.log(
                    f"[Orchestrator] Auto-loaded human-edited CurationResult from session "
                    f"({len(effective_preset.topics)} topics); Curator will be skipped"
                )
            except Exception as e:
                # Defensive: if load fails, fall through to normal Curator execution
                cb.log(f"[WARN] Failed to load curation_result.json ({e}); running Curator normally")
                effective_preset = None

        cb.log(f"[Orchestrator] Long-form script generation with {context.provider} (TopicCuration → SegmentGeneration)")
        orchestrator = ScriptOrchestrator(context)
        script = await orchestrator.generate_script(
            theme=research_brief.theme,
            research_data=research_data,
            avoid_topics=avoid_topics,
            excluded_topics=excluded_topics,
            progress_callback=cb,
            preset_curation=effective_preset,
        )
        llm_usage = orchestrator.get_total_usage()
        segments = orchestrator.segments
    else:
        # Single API call (fallback) - still uses provider selection
        script_generator = create_script_generator(config, provider=context.provider)
        script = await script_generator.generate(
            research_brief.theme,
            research_data,
            avoid_topics=avoid_topics,
            excluded_topics=excluded_topics
        )
        llm_usage = script_generator.last_usage
    
    # Speaker diagnostics and auto-correction
    phase_label = "Part 2" if excluded_topics and excluded_topics.strip() else "Part 1/Single"
    diagnostics, suspected_swap = _build_speaker_diagnostics(script, label=phase_label)
    for msg in diagnostics:
        cb.log(msg)
    
    if suspected_swap:
        cb.log("[WARN] Detected speaker role swap based on speech patterns. Applying auto-correction...")
        script = _swap_script_speakers(script)
        fixed_diagnostics, _ = _build_speaker_diagnostics(script, label=f"{phase_label} (fixed)")
        for msg in fixed_diagnostics:
            cb.log(msg)
    
    script_duration = time.time() - script_start
    cb.log(f"✓ Script generation completed: {len(script.sections)} phrases ({script_duration:.1f}s)")
    cb.log(f"Title: {script.title}")
    cb.progress(0.65, "✅ Script generation completed")
    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    
    # Save script (backward compatibility)
    script_path = session_manager.session_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    cb.log(f"✓ Script saved: {script_path.name}")
    
    # Step 2: Visual Identity Generation (for dynamic background mode)
    visual_identity = None
    video_config = getattr(config.yaml, "video_renderer", None)
    background_mode = getattr(video_config, "background_mode", "static") if video_config else "static"
    
    if background_mode == "dynamic":
        # Skip VisualPaletteGenerator for Ollama (Gemini-only feature)
        if provider.lower() == "ollama":
            cb.log("\n== Scripting Phase: Visual Identity Generation ==")
            cb.log("[INFO] Ollama provider detected: Skipping visual identity generation (Gemini-only feature)")
            cb.log("[INFO] Using default visual identity")
            cb.progress(0.70, "⚡ Using default visual identity (Ollama)")
            await asyncio.sleep(0)
            
            from core.models.visual import (
                VisualIdentity,
                DEFAULT_PRIMARY_COLOR,
                DEFAULT_SECONDARY_COLOR,
                DEFAULT_COLOR_MOOD,
                DEFAULT_AESTHETIC,
                DEFAULT_VISUAL_KEYWORDS
            )
            visual_identity = VisualIdentity(
                primary_color=DEFAULT_PRIMARY_COLOR,
                secondary_color=DEFAULT_SECONDARY_COLOR,
                color_mood=DEFAULT_COLOR_MOOD,
                aesthetic=DEFAULT_AESTHETIC,
                visual_keywords=list(DEFAULT_VISUAL_KEYWORDS)  # Convert tuple to list
            )
        else:
            try:
                cb.log("\n== Scripting Phase: Visual Identity Generation ==")
                cb.log("[INFO] Generating visual brand (color + style) for FLUX.1...")
                cb.progress(0.70, "🎨 Generating visual identity...")
                await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
                
                from services.script_generation.visual_palette_generator import VisualPaletteGenerator
                
                palette_generator = VisualPaletteGenerator(config)
                script_summary = script.description[:300] if script.description else research_brief.theme
                
                visual_identity = await palette_generator.generate_palette(
                    theme=research_brief.theme,
                    script_summary=script_summary
                )
                
                cb.log(f"✓ Visual identity determined: {visual_identity}")
                cb.progress(0.80, "✅ Visual identity generated")
                await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
            except Exception as e:
                cb.log(f"⚠ Visual identity generation failed: {e}")
                cb.log("[INFO] Using default visual identity")
                from core.models.visual import (
                    VisualIdentity,
                    DEFAULT_PRIMARY_COLOR,
                    DEFAULT_SECONDARY_COLOR,
                    DEFAULT_COLOR_MOOD,
                    DEFAULT_AESTHETIC,
                    DEFAULT_VISUAL_KEYWORDS
                )
                visual_identity = VisualIdentity(
                    primary_color=DEFAULT_PRIMARY_COLOR,
                    secondary_color=DEFAULT_SECONDARY_COLOR,
                    color_mood=DEFAULT_COLOR_MOOD,
                    aesthetic=DEFAULT_AESTHETIC,
                    visual_keywords=list(DEFAULT_VISUAL_KEYWORDS)  # Convert tuple to list
                )
                cb.progress(0.80, "⚠️ Using default visual identity")
                await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    else:
        cb.log("[INFO] Static mode: Skipping visual identity generation")
        cb.progress(0.80, "⏭️ Skipping visual identity generation")
    
    # Step 3: Metadata Generation
    cb.log("\n== Scripting Phase: Metadata Generation ==")
    cb.progress(0.85, "🔖 Generating metadata...")
    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    
    try:
        from services.script_generation.metadata_generator import MetadataGenerator
        
        # Create LLM port for metadata generation
        llm_port = context.create_llm_port()
        
        metadata_generator = MetadataGenerator(llm_port, config)
        script = await metadata_generator.generate(
            theme=research_brief.theme,
            script=script,
            research_data=research_data,
            progress_log=cb.log
        )
        
        cb.log(f"✓ Metadata generated: {script.title}")
        cb.progress(0.90, "✅ Metadata generation completed")
    except Exception as e:
        cb.log(f"⚠ Metadata generation failed (using defaults): {e}")
        cb.progress(0.90, "⚠️ Using default metadata")
    
    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    
    # Step 4: Build RadioScriptArtifact
    cb.progress(0.95, "📦 Building script artifact...")
    await asyncio.sleep(0)  # Yield to event loop for Gradio progress flush
    script_artifact = RadioScriptArtifact(
        session_id=session_manager.session_id,
        script=script,
        segments=[_to_json_safe(seg.model_dump()) for seg in segments] if segments else None,
        visual_identity=_to_json_safe(visual_identity.model_dump()) if visual_identity else None,
        research_brief_path="research_brief.json",
        llm_usage=_to_json_safe(asdict(llm_usage)) if llm_usage else None,
    )
    
    # Save RadioScriptArtifact
    saved_path = session_manager.save_script_artifact(script_artifact)
    cb.log(f"✓ RadioScriptArtifact saved: {saved_path}")
    
    cb.progress(1.0, "✅ Scripting phase completed")
    cb.log(f"✓ Scripting phase completed ({script_duration:.1f}s)")
    
    return script_artifact
