"""Single-image FFmpeg rendering path.

セグメント単位の動的背景を使わず、1 枚の背景画像で動画全体を合成する
モノリシック FFmpeg レンダリング経路。`segments` 引数なしで FFmpegRenderer
が呼び出された際に backward-compatible なフォールバックとして稼働する。
"""
import asyncio
from pathlib import Path

from rich.console import Console

from core.interfaces import ChapterMarker, RenderResult, SynthesisResult

console = Console()


async def render_single_image(
    renderer,
    synthesis_result: SynthesisResult,
    background_image: Path,
    bgm_file: Path,
    output_path: Path,
    subtitle_path: Path,
    chapters: list[ChapterMarker],
) -> RenderResult:
    """Render a video using a single background image for the whole duration.

    モノリシック FFmpeg コマンドで 1 枚の背景画像と音声/BGM/字幕を合成する。
    `segments` が指定されていない呼び出し（後方互換パス）で使用される。
    """
    console.print("[cyan]動画を生成中（単一背景画像モード）...[/cyan]")
    
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
        file_size_mb=file_size_mb,
        segment_bg_generation_time=0.0  # Legacy mode does not generate dynamic backgrounds
    )
