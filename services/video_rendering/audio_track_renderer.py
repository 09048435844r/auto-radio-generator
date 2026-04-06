"""Audio track renderer for Phase B of 3-phase pipeline

Renders complete audio track with:
- Main audio (VOICEVOX synthesis)
- BGM (with fade in/out and volume control)
- Jingles (inserted at segment boundaries)
- Loudness normalization (YouTube standard: -14 LUFS)
"""
import asyncio
import logging
import shutil
from pathlib import Path

from rich.console import Console

from core.models import AppConfig, VideoTimeline

logger = logging.getLogger(__name__)
console = Console()


class AudioTrackRenderer:
    """Audio track renderer
    
    Generates a complete mixed audio track from timeline information.
    This is Phase B (Audio) of the 3-phase rendering pipeline.
    """
    
    def __init__(self, config: AppConfig):
        """Initialize audio track renderer
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.ffmpeg_path = self._find_ffmpeg()
        
        # Cache video config settings for BGM ducking
        video_config = getattr(config.yaml, "video_renderer", None)
        self.enable_ducking = getattr(video_config, "enable_bgm_ducking", False) if video_config else False
        self.ducking_level = getattr(video_config, "bgm_ducking_level", 0.04) if video_config else 0.04
    
    def _find_ffmpeg(self) -> str:
        """Find FFmpeg executable path"""
        # Check project root
        project_ffmpeg = self.config.project_root.parent / "ffmpeg.exe"
        if project_ffmpeg.exists():
            return str(project_ffmpeg)
        
        # Check PATH
        ffmpeg_in_path = shutil.which("ffmpeg")
        if ffmpeg_in_path:
            return ffmpeg_in_path
        
        return "ffmpeg"
    
    async def render_audio_track(
        self,
        timeline: VideoTimeline,
        output_path: Path,
    ) -> Path:
        """Render complete audio track
        
        Args:
            timeline: Video timeline with all segment and audio information
            output_path: Output audio file path (e.g., temp_audio_track.wav)
        
        Returns:
            Path: Generated audio track path
        """
        console.print("[cyan]Rendering audio track...[/cyan]")
        
        # Build FFmpeg command
        cmd = self._build_ffmpeg_command(timeline, output_path)
        
        # Debug output
        console.print(f"[dim]Audio track inputs: main + BGM + {self._count_jingles(timeline)} jingles[/dim]")
        
        # Execute FFmpeg
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace')
            logger.error(f"Audio track rendering failed: {error_msg}")
            logger.error(f"FFmpeg command: {' '.join(cmd)}")
            console.print(f"[red]✗ Audio track rendering failed[/red]")
            console.print(f"[red]FFmpeg error output:[/red]")
            console.print(f"[dim]{error_msg}[/dim]")
            raise RuntimeError(f"FFmpeg audio rendering failed with code {process.returncode}\n\nFFmpeg error:\n{error_msg}")
        
        console.print(f"[green]✓ Audio track rendered: {output_path.name}[/green]")
        return output_path
    
    def _build_ffmpeg_command(self, timeline: VideoTimeline, output_path: Path) -> list[str]:
        """Build FFmpeg command for audio track rendering
        
        Args:
            timeline: Video timeline
            output_path: Output file path
        
        Returns:
            list[str]: FFmpeg command arguments
        """
        # Input files
        # [0] = Main audio (VOICEVOX)
        # [1] = BGM
        # [2..N] = Jingles (if any)
        
        input_args = [
            "-i", str(timeline.main_audio_path),
            "-stream_loop", "-1", "-i", str(timeline.bgm_path),
        ]
        
        # Collect jingles
        jingle_segments = [seg for seg in timeline.segments if seg.jingle_path]
        for seg in jingle_segments:
            input_args.extend(["-i", str(seg.jingle_path)])
        
        # Build filter_complex
        filter_parts = []
        
        # 1. BGM processing: volume + fade in/out
        bgm_filter = self._build_bgm_filter(timeline)
        filter_parts.append(bgm_filter)
        
        # 2. Jingle processing: delay to correct timing
        if jingle_segments:
            jingle_filters = self._build_jingle_filters(jingle_segments)
            filter_parts.extend(jingle_filters)
        
        # 3. Mix all audio streams
        mix_filter = self._build_mix_filter(len(jingle_segments))
        filter_parts.append(mix_filter)
        
        # 4. Loudness normalization (YouTube standard)
        normalize_filter = "[mixed]loudnorm=I=-14:TP=-1:LRA=11[aout]"
        filter_parts.append(normalize_filter)
        
        filter_complex = ";".join(filter_parts)
        
        cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite output
            *input_args,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "pcm_s16le",  # Uncompressed WAV (avoid re-encoding in muxing phase)
            "-ar", "48000",       # 48kHz sample rate
            "-ac", "2",           # Stereo
            str(output_path)
        ]
        
        return cmd
    
    def _build_bgm_filter(self, timeline: VideoTimeline) -> str:
        """Build BGM filter with volume, fade in/out, and ducking during jingles
        
        Args:
            timeline: Video timeline
        
        Returns:
            str: BGM filter string
        """
        fade_out_start = max(0, timeline.total_duration_sec - timeline.fade_out_sec)
        normal_level = timeline.bgm_volume
        
        # Collect jingle periods for ducking
        jingle_periods = []
        if self.enable_ducking:
            for seg in timeline.segments:
                if seg.jingle_start_sec is not None and seg.jingle_duration_sec is not None:
                    start = seg.jingle_start_sec
                    end = start + seg.jingle_duration_sec
                    jingle_periods.append((start, end))
        
        # Build filter with or without ducking
        if jingle_periods:
            # Guard against invalid volume settings
            if normal_level <= 0 or self.ducking_level < 0:
                logger.warning(
                    f"Invalid volume settings (normal={normal_level}, ducking={self.ducking_level}), ducking disabled"
                )
                # No ducking (fallback to original behavior)
                return (
                    f"[1:a]volume={timeline.bgm_volume},"
                    f"afade=t=in:st=0:d={timeline.fade_in_sec},"
                    f"afade=t=out:st={fade_out_start}:d={timeline.fade_out_sec}[bgm]"
                )
            
            # Validate ducking level to prevent volume increase
            ducking_level = self.ducking_level
            if ducking_level >= normal_level:
                logger.warning(
                    f"Ducking level ({ducking_level}) >= normal level ({normal_level}), "
                    f"clamping to {normal_level * 0.25:.4f}"
                )
                ducking_level = normal_level * 0.25
            
            # Calculate ducking multiplier (ratio to apply during jingle periods)
            ducking_multiplier = ducking_level / normal_level
            
            # Build between conditions using + for OR (FFmpeg expression syntax)
            between_conditions = "+".join(
                f"between(t,{start},{end})" for start, end in jingle_periods
            )
            
            # Two-stage volume control:
            # 1. Set base volume to normal level
            # 2. Apply ducking multiplier during jingle periods
            return (
                f"[1:a]volume={normal_level},"
                f"volume={ducking_multiplier}:enable='{between_conditions}',"
                f"afade=t=in:st=0:d={timeline.fade_in_sec},"
                f"afade=t=out:st={fade_out_start}:d={timeline.fade_out_sec}[bgm]"
            )
        else:
            # No ducking (original behavior)
            return (
                f"[1:a]volume={timeline.bgm_volume},"
                f"afade=t=in:st=0:d={timeline.fade_in_sec},"
                f"afade=t=out:st={fade_out_start}:d={timeline.fade_out_sec}[bgm]"
            )
    
    def _build_jingle_filters(self, jingle_segments: list) -> list[str]:
        """Build jingle filters with delay for correct timing
        
        Args:
            jingle_segments: Segments with jingles
        
        Returns:
            list[str]: List of jingle filter strings
        """
        filters = []
        
        for i, seg in enumerate(jingle_segments):
            if seg.jingle_start_sec is None:
                continue
            
            # Calculate delay in milliseconds
            delay_ms = int(seg.jingle_start_sec * 1000)
            
            # Input index: 0=main, 1=bgm, 2+=jingles
            input_idx = i + 2
            
            # Apply delay to position jingle at correct time
            filters.append(f"[{input_idx}:a]adelay=delays={delay_ms}|{delay_ms}[jingle{i}]")
        
        return filters
    
    def _build_mix_filter(self, jingle_count: int) -> str:
        """Build audio mixing filter
        
        Args:
            jingle_count: Number of jingles
        
        Returns:
            str: Mix filter string
        """
        # Combine: main audio + BGM + all jingles
        inputs = ["[0:a]", "[bgm]"]
        inputs.extend([f"[jingle{i}]" for i in range(jingle_count)])
        
        input_str = "".join(inputs)
        n = len(inputs)
        
        # amix: mix multiple audio streams
        # duration=first: use duration of first input (main audio)
        # dropout_transition: smooth transition when streams end
        return f"{input_str}amix=inputs={n}:duration=first:dropout_transition=2[mixed]"
    
    def _count_jingles(self, timeline: VideoTimeline) -> int:
        """Count number of jingles in timeline
        
        Args:
            timeline: Video timeline
        
        Returns:
            int: Number of jingles
        """
        return sum(1 for seg in timeline.segments if seg.jingle_path)
