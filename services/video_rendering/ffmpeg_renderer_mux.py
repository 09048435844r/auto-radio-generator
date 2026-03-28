"""Muxing utilities for Phase C of 3-phase pipeline

Combines video and audio tracks without re-encoding (fast operation).
"""
import asyncio
from pathlib import Path

from rich.console import Console

console = Console()


async def mux_tracks(
    ffmpeg_path: str,
    video_track: Path,
    audio_track: Path,
    output_path: Path,
) -> None:
    """Mux video and audio tracks without re-encoding
    
    Args:
        ffmpeg_path: Path to FFmpeg executable
        video_track: Video track file path
        audio_track: Audio track file path
        output_path: Output video file path
    
    Raises:
        RuntimeError: If muxing fails
    """
    cmd = [
        ffmpeg_path,
        "-y",  # Overwrite output
        "-i", str(video_track),
        "-i", str(audio_track),
        "-c:v", "copy",  # No re-encoding (fast)
        "-c:a", "aac",   # Convert to AAC for MP4 compatibility
        "-b:a", "192k",  # Audio bitrate
        "-shortest",     # Stop at shortest stream
        str(output_path)
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_msg = stderr.decode('utf-8', errors='replace')
        console.print(f"[red]✗ Muxing failed[/red]")
        raise RuntimeError(f"Muxing failed: {error_msg}")
    
    console.print(f"[green]✓ Muxing完了: {output_path.name}[/green]")
