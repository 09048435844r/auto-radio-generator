"""Timeline calculator for segment-based video rendering

Calculates detailed timeline information from script segments and audio synthesis results.
This is Phase A of the 3-phase rendering pipeline.
"""
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console

from core.models import AppConfig, ScriptSegment, SegmentTimelineEntry, VideoTimeline
from core.interfaces import SynthesisResult, SegmentTiming
from services.media_processing import ImageProvider, JingleProvider

logger = logging.getLogger(__name__)
console = Console()


class TimelineCalculator:
    """Timeline calculation engine
    
    Constructs detailed video timeline from script segments and audio timing information.
    This is the foundation for Phase B (Independent Rendering).
    """
    
    def __init__(self, config: AppConfig):
        """Initialize timeline calculator
        
        Args:
            config: Application configuration
        """
        self.config = config
        
        # Get jingle settings from config
        video_config = getattr(config.yaml, "video_renderer", None)
        self.jingle_overlap_sec = getattr(video_config, "jingle_overlap_sec", 3.0) if video_config else 3.0
        self.enable_jingles = getattr(video_config, "enable_jingles", True) if video_config else True
        self.pre_jingle_pause_sec = getattr(video_config, "pre_jingle_pause_sec", 0.5) if video_config else 0.5
    
    async def calculate_timeline(
        self,
        segments: list[ScriptSegment],
        synthesis_result: SynthesisResult,
        image_provider: ImageProvider,
        jingle_provider: JingleProvider,
        bgm_path: Path,
    ) -> VideoTimeline:
        """Calculate complete video timeline
        
        Args:
            segments: Script segments from TopicCurator/SegmentGenerator
            synthesis_result: Audio synthesis result with segment timings
            image_provider: Background image provider
            jingle_provider: Jingle audio provider
            bgm_path: BGM file path
        
        Returns:
            VideoTimeline: Complete timeline with all segment information
        """
        console.print("[cyan]Calculating video timeline...[/cyan]")
        
        timeline_entries = []
        
        for i, segment in enumerate(segments):
            # Find corresponding audio timing
            timing = self._find_timing_for_segment(segment, synthesis_result.segment_timings)
            
            if not timing:
                logger.warning(f"No timing found for segment {segment.segment_id}, using estimated timing")
                # Estimate timing based on position
                timing = self._estimate_timing(segment, i, len(segments), synthesis_result.total_duration_sec)
            
            # Get background image for this segment
            bg_image = await image_provider.get_image_for_segment(segment)
            
            # Determine jingle for segment boundary (not for last segment)
            jingle_path = None
            jingle_start = None
            jingle_duration = None
            
            if self.enable_jingles and i < len(segments) - 1 and jingle_provider.is_available():
                jingle_path = jingle_provider.get_random_jingle()
                if jingle_path:
                    jingle_duration = jingle_provider.get_jingle_duration(jingle_path)
                    # Validate jingle duration
                    if jingle_duration is None or jingle_duration <= 0:
                        logger.warning(f"Invalid jingle duration ({jingle_duration}) for {jingle_path.name}, skipping jingle")
                        jingle_path = None
                        jingle_duration = None
                    else:
                        # Start jingle after pre-jingle pause (breathing space before jingle)
                        # Pause structure: [segment end] + [pre-pause] + [jingle]
                        jingle_start = timing.end_sec + self.pre_jingle_pause_sec
                        logger.debug(
                            f"Jingle for segment {segment.segment_id}: {jingle_path.name} "
                            f"at {jingle_start:.2f}s (pre-pause: {self.pre_jingle_pause_sec:.2f}s, "
                            f"duration: {jingle_duration:.2f}s)"
                        )
            
            # Calculate video timing (for jingle-synchronized transitions)
            # If jingle exists, extend video display until jingle ends (including pre-pause)
            if jingle_path and jingle_duration and jingle_duration > 0:
                total_pause_duration = self.pre_jingle_pause_sec + jingle_duration
                video_duration = timing.duration_sec + total_pause_duration
                video_cut_time = timing.end_sec + total_pause_duration
            else:
                video_duration = timing.duration_sec
                video_cut_time = timing.end_sec
            
            timeline_entries.append(SegmentTimelineEntry(
                segment_id=segment.segment_id,
                segment_type=segment.segment_type,
                topic_title=segment.topic_title,
                audio_start_sec=timing.start_sec,
                audio_end_sec=timing.end_sec,
                duration_sec=timing.duration_sec,
                video_duration_sec=video_duration,
                video_cut_time_sec=video_cut_time,
                background_image_path=bg_image,
                jingle_path=jingle_path,
                jingle_start_sec=jingle_start,
                jingle_duration_sec=jingle_duration,
            ))
            
            console.print(
                f"[dim]  Segment {i+1}/{len(segments)}: {segment.segment_id} "
                f"({timing.start_sec:.1f}s - {timing.end_sec:.1f}s, "
                f"image: {bg_image.name})[/dim]"
            )
        
        # Calculate total duration including pre-jingle pauses
        # Count jingles (all segments except last)
        jingle_count = sum(1 for entry in timeline_entries if entry.jingle_path is not None)
        total_pause_duration = jingle_count * self.pre_jingle_pause_sec
        total_duration_with_pauses = synthesis_result.total_duration_sec + total_pause_duration
        
        logger.debug(
            f"Timeline duration: audio={synthesis_result.total_duration_sec:.2f}s, "
            f"jingles={jingle_count}, pre-pause={total_pause_duration:.2f}s, "
            f"total={total_duration_with_pauses:.2f}s"
        )
        
        # Get video settings from config
        video_config = self.config.yaml.video_renderer
        
        timeline = VideoTimeline(
            segments=timeline_entries,
            total_duration_sec=total_duration_with_pauses,  # Include pre-jingle pauses
            main_audio_path=synthesis_result.audio_path,
            bgm_path=bgm_path,
            bgm_volume=video_config.bgm_volume,
            fade_in_sec=video_config.bgm_fade_in_sec,
            fade_out_sec=video_config.bgm_fade_out_sec,
            resolution=video_config.output_resolution,
            fps=video_config.output_fps,
            subtitle_path=synthesis_result.subtitle_path,
        )
        
        console.print(f"[green]✓ Timeline calculated: {len(timeline_entries)} segments[/green]")
        
        return timeline
    
    def _find_timing_for_segment(
        self,
        segment: ScriptSegment,
        segment_timings: list[SegmentTiming]
    ) -> Optional[SegmentTiming]:
        """Find audio timing for a segment
        
        Args:
            segment: Script segment
            segment_timings: List of segment timings from audio synthesis
        
        Returns:
            SegmentTiming: Matching timing, or None if not found
        """
        for timing in segment_timings:
            if timing.segment_id == segment.segment_id:
                return timing
        
        return None
    
    def _estimate_timing(
        self,
        segment: ScriptSegment,
        index: int,
        total_segments: int,
        total_duration: float
    ) -> SegmentTiming:
        """Estimate timing for a segment (fallback)
        
        Args:
            segment: Script segment
            index: Segment index
            total_segments: Total number of segments
            total_duration: Total audio duration
        
        Returns:
            SegmentTiming: Estimated timing
        """
        # Simple linear estimation
        segment_duration = total_duration / total_segments
        start_sec = index * segment_duration
        end_sec = start_sec + segment_duration
        
        logger.warning(
            f"Using estimated timing for segment {segment.segment_id}: "
            f"{start_sec:.1f}s - {end_sec:.1f}s"
        )
        
        return SegmentTiming(
            segment_id=segment.segment_id,
            segment_type=segment.segment_type,
            topic_title=segment.topic_title,
            start_sec=start_sec,
            end_sec=end_sec,
            duration_sec=segment_duration,
        )
