"""動画生成フェーズ実行サービス

RadioScriptArtifactを入力として音声合成と動画レンダリングを実行する。
"""
from pathlib import Path
from typing import Optional

from core.models import AppConfig
from core.models.script import RadioScriptArtifact
from core.session_manager import SessionManager
from workflow import (
    ProgressCallback,
    ProductionPhaseResult,
    execute_production_phase as workflow_execute_production_phase
)


async def execute_production_phase(
    script_artifact: RadioScriptArtifact,
    session_manager: SessionManager,
    config: AppConfig,
    project_root: Path,
    speed_scale: Optional[float] = None,
    background_image: Optional[str] = None,
    bgm_file: Optional[str] = None,
    callbacks: Optional[ProgressCallback] = None
) -> ProductionPhaseResult:
    """Execute production phase (audio synthesis + video rendering)
    
    Args:
        script_artifact: RadioScriptArtifact from scripting phase
        session_manager: SessionManager instance
        config: Application config
        project_root: Project root directory
        speed_scale: Audio speed multiplier (optional)
        background_image: Background image filename override (optional)
        bgm_file: BGM filename override (optional)
        callbacks: Progress callback
        
    Returns:
        ProductionPhaseResult: Production phase result
    """
    cb = callbacks or ProgressCallback()
    
    cb.log(f"\n== Production Phase: Audio Synthesis & Video Rendering ==")
    
    # Convert RadioScriptArtifact to parameters for workflow function
    from core.models.curation import ScriptSegment
    
    segments = None
    if script_artifact.segments:
        segments = [ScriptSegment.model_validate(seg_dict) for seg_dict in script_artifact.segments]
    
    visual_identity = None
    if script_artifact.visual_identity:
        from core.models.visual import VisualIdentity
        visual_identity = VisualIdentity.model_validate(script_artifact.visual_identity)
    
    # Use session directory as output directory
    output_dir = session_manager.session_dir
    
    # Execute production phase using existing workflow function
    result = await workflow_execute_production_phase(
        script=script_artifact.script,
        config=config,
        output_dir=output_dir,
        project_root=project_root,
        speed_scale=speed_scale,
        segments=segments,
        visual_identity=visual_identity,
        callbacks=cb
    )
    
    cb.log(f"✓ Production phase completed")
    cb.log(f"Video: {result.video_path}")
    cb.log(f"Duration: {result.duration_sec:.1f}s")
    cb.log(f"File size: {result.file_size_mb:.1f}MB")
    
    return result
