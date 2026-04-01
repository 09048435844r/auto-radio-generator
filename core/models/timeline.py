"""Timeline data models for segment-based video rendering

This module defines the timeline structure used by the 3-phase rendering pipeline:
- Phase A: Timeline Calculation
- Phase B: Independent Rendering (Video Track + Audio Track)
- Phase C: Muxing
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SegmentTimelineEntry:
    """Timeline information for a single segment
    
    Represents when a segment starts/ends, which background image to use,
    and whether a jingle should be inserted at the segment boundary.
    """
    segment_id: str                           # "intro", "deep_dive_1", "conclusion", etc.
    segment_type: str                         # "intro" | "deep_dive" | "conclusion"
    topic_title: Optional[str]                # Topic title for deep_dive segments
    
    # Timing information
    audio_start_sec: float                    # Segment audio start time
    audio_end_sec: float                      # Segment audio end time
    duration_sec: float                       # Segment duration (audio only)
    
    # Video timing information (for jingle-synchronized transitions)
    video_duration_sec: float                 # Video display duration (includes jingle if present)
    video_cut_time_sec: float                 # Time when video cuts to next segment
    
    # Asset information
    background_image_path: Path               # Background image for this segment
    jingle_path: Optional[Path] = None        # Jingle to insert at segment boundary
    jingle_start_sec: Optional[float] = None  # Jingle start time (e.g., 1 sec before segment end)
    jingle_duration_sec: Optional[float] = None  # Jingle duration
    pause_after_sec: Optional[float] = None   # Pause duration inserted after this segment


@dataclass
class VideoTimeline:
    """Complete video timeline with all segments and audio settings
    
    This is the output of Phase A (Timeline Calculation) and serves as
    input for Phase B (Independent Rendering).
    """
    segments: list[SegmentTimelineEntry]
    total_duration_sec: float
    
    # Audio track settings
    main_audio_path: Path                     # Main audio (VOICEVOX output)
    bgm_path: Path                            # BGM file
    bgm_volume: float                         # BGM volume (0.0 - 1.0)
    fade_in_sec: float                        # BGM fade-in duration
    fade_out_sec: float                       # BGM fade-out duration
    
    # Video track settings
    resolution: str = "1920x1080"             # Output resolution
    fps: int = 30                             # Output FPS
    subtitle_path: Optional[Path] = None      # Subtitle file (.ass)
