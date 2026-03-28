"""Legacy rendering methods for backward compatibility

These methods implement the original monolithic FFmpeg approach
and are used when segments are not provided.
"""
import asyncio
from pathlib import Path

from rich.console import Console

from core.interfaces import ChapterMarker, RenderResult, SynthesisResult

console = Console()


async def render_legacy(
    renderer,
    synthesis_result: SynthesisResult,
    background_image: Path,
    bgm_file: Path,
    output_path: Path,
    subtitle_path: Path,
    chapters: list[ChapterMarker],
) -> RenderResult:
    """Legacy rendering method (single background image)
    
    This is the original monolithic FFmpeg approach.
    Used for backward compatibility when segments are not provided.
    """
    console.print("[cyan]動画を生成中（レガシーモード）...[/cyan]")
    
    # 設定値
    resolution = renderer.video_config.output_resolution
    fps = renderer.video_config.output_fps
    bgm_volume = renderer.video_config.bgm_volume
    fade_in = renderer.video_config.bgm_fade_in_sec
    fade_out = renderer.video_config.bgm_fade_out_sec
    total_duration = synthesis_result.total_duration_sec
    
    # FFmpegコマンドを構築
    cmd = renderer._build_ffmpeg_command(
        background_image=background_image,
        audio_file=synthesis_result.audio_path,
        bgm_file=bgm_file,
        subtitle_file=subtitle_path,
        output_path=output_path,
        resolution=resolution,
        fps=fps,
        bgm_volume=bgm_volume,
        fade_in_sec=fade_in,
        fade_out_sec=fade_out,
        total_duration_sec=total_duration,
        chapters=chapters,
    )
    
    # 非同期でFFmpegを実行
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_msg = stderr.decode('utf-8', errors='replace')
        console.print(f"[red]✗ FFmpeg エラー:[/red]\n{error_msg[-1000:]}")
        raise RuntimeError(f"FFmpeg failed with code {process.returncode}")
    
    # 結果を返す
    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    
    console.print(f"[green]OK 動画生成完了[/green] {output_path.name}")
    console.print(f"  → サイズ: {file_size_mb:.1f} MB, 長さ: {total_duration:.1f}秒")
    
    return RenderResult(
        video_path=output_path,
        duration_sec=total_duration,
        file_size_mb=file_size_mb
    )
