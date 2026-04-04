"""台本作成フェーズ実行サービス

ResearchBriefを入力として台本を生成し、RadioScriptArtifactを生成する。
"""
import time
from typing import Optional
from dataclasses import asdict

from core.models import AppConfig
from core.models.artifacts import ResearchBrief
from core.models.script import RadioScriptArtifact
from core.session_manager import SessionManager
from core.interfaces import ResearchResult
from workflow import (
    ProgressCallback,
    create_script_generator,
    _build_speaker_diagnostics,
    _swap_script_speakers,
    _to_json_safe
)


async def execute_scripting_phase(
    research_brief: ResearchBrief,
    session_manager: SessionManager,
    config: AppConfig,
    excluded_topics: Optional[str] = None,
    avoid_topics: Optional[str] = None,
    provider: str = "gemini",
    callbacks: Optional[ProgressCallback] = None
) -> RadioScriptArtifact:
    """Execute scripting phase and generate RadioScriptArtifact
    
    Args:
        research_brief: ResearchBrief from research phase
        session_manager: SessionManager instance
        config: Application config
        excluded_topics: Topics to exclude (for multi-part scripts)
        avoid_topics: Topics to avoid (Negative Prompt, optional)
        provider: LLM provider ("gemini" | "openai" | "anthropic")
        callbacks: Progress callback
        
    Returns:
        RadioScriptArtifact: Scripting phase output artifact
    """
    cb = callbacks or ProgressCallback()
    
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
    
    use_orchestrator = config.yaml.script_generator.orchestrator.enabled
    cb.log(f"Engine: {'ScriptOrchestrator (Agentic)' if use_orchestrator else provider}")
    cb.progress(0.50, f"📝 Generating script ({'Orchestrator' if use_orchestrator else provider})...")
    
    script_start = time.time()
    segments = None
    
    if use_orchestrator and research_data is not None:
        # Hierarchical Agentic Workflow
        from services.script_generation.orchestrator import ScriptOrchestrator
        
        cb.log("[Orchestrator] Long-form script generation (TopicCuration → SegmentGeneration)")
        orchestrator = ScriptOrchestrator(config)
        script = await orchestrator.generate_script(
            theme=research_brief.theme,
            research_data=research_data,
            avoid_topics=avoid_topics,
            excluded_topics=excluded_topics,
            progress_callback=cb,
        )
        llm_usage = orchestrator.get_total_usage()
        segments = orchestrator.segments
    else:
        # Single API call (fallback)
        script_generator = create_script_generator(config, provider=provider)
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
    
    # Save script (backward compatibility)
    script_path = session_manager.session_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    cb.log(f"✓ Script saved: {script_path.name}")
    
    # Step 2: Visual Identity Generation (for dynamic background mode)
    visual_identity = None
    video_config = getattr(config.yaml, "video_renderer", None)
    background_mode = getattr(video_config, "background_mode", "static") if video_config else "static"
    
    if background_mode == "dynamic":
        try:
            cb.log("\n== Scripting Phase: Visual Identity Generation ==")
            cb.log("[INFO] Generating visual brand (color + style) for FLUX.1...")
            
            from services.script_generation.visual_palette_generator import VisualPaletteGenerator
            
            palette_generator = VisualPaletteGenerator(config)
            script_summary = script.description[:300] if script.description else research_brief.theme
            
            visual_identity = await palette_generator.generate_palette(
                theme=research_brief.theme,
                script_summary=script_summary
            )
            
            cb.log(f"✓ Visual identity determined: {visual_identity}")
        except Exception as e:
            cb.log(f"⚠ Visual identity generation failed: {e}")
            cb.log("[INFO] Falling back to default colors")
            visual_identity = None
    else:
        cb.log("[INFO] Static mode: Skipping visual identity generation")
    
    # Step 3: Build RadioScriptArtifact
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
    
    cb.log(f"✓ Scripting phase completed ({script_duration:.1f}s)")
    
    return script_artifact
