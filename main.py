"""自動ラジオ動画生成システム - メインエントリーポイント"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import load_config, Script
from core.interfaces import IScriptGenerator
from services.script_generation import GeminiClient, PerplexityClient
from services.audio_synthesis import VoicevoxClient
from services.video_rendering import FfmpegRenderer

console = Console()


def create_script_generator(config) -> IScriptGenerator:
    """設定に基づいて台本生成エンジンを作成"""
    engine = config.yaml.script_generator.engine
    
    if engine == "gemini":
        return GeminiClient(config)
    elif engine == "perplexity":
        return PerplexityClient(config)
    else:
        raise ValueError(f"Unknown script generator engine: {engine}")


async def main():
    """メイン処理"""
    console.print(Panel.fit(
        "[bold cyan]🎙️ 自動ラジオ動画生成システム[/bold cyan]",
        border_style="cyan"
    ))
    
    # 設定を読み込み
    console.print("\n[dim]設定を読み込み中...[/dim]")
    config = load_config(PROJECT_ROOT)
    
    # エンジン状態を確認
    console.print("\n[bold]== エンジン状態確認 ==[/bold]")
    
    # VOICEVOX確認
    voicevox = VoicevoxClient(config)
    if not await voicevox.check_engine_status():
        console.print("[red]VOICEVOXエンジンを起動してから再実行してください。[/red]")
        return
    
    # FFmpeg確認
    ffmpeg = FfmpegRenderer(config)
    if not ffmpeg.check_ffmpeg_available():
        console.print("[red]FFmpegをインストールしてから再実行してください。[/red]")
        return
    
    # テーマを入力
    console.print("\n[bold]== 台本生成 ==[/bold]")
    theme = Prompt.ask(
        "[cyan]動画のテーマを入力してください[/cyan]",
        default="今週の面白いニュースについて"
    )
    
    # 台本を生成
    script_generator = create_script_generator(config)
    script = await script_generator.generate(theme)
    
    # 台本のプレビュー
    console.print("\n[bold]== 生成された台本 ==[/bold]")
    console.print(Panel(
        f"[bold]{script.title}[/bold]\n\n{script.description}",
        title="タイトル & 概要",
        border_style="green"
    ))
    
    # 対話の一部を表示
    console.print("\n[dim]対話プレビュー（最初の5行）:[/dim]")
    for line in script.dialogue[:5]:
        speaker_color = "yellow" if line.speaker == "A" else "magenta"
        console.print(f"  [{speaker_color}][{line.speaker}][/{speaker_color}] {line.text[:50]}...")
    if len(script.dialogue) > 5:
        console.print(f"  [dim]... 他 {len(script.dialogue) - 5} 行[/dim]")
    
    # 続行確認
    proceed = Prompt.ask(
        "\n[cyan]この台本で動画を生成しますか？[/cyan]",
        choices=["y", "n"],
        default="y"
    )
    
    if proceed.lower() != "y":
        console.print("[yellow]キャンセルしました。[/yellow]")
        return
    
    # 出力ディレクトリを準備
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = PROJECT_ROOT / config.yaml.paths.output_dir / timestamp
    audio_output_dir = output_base / "audio"
    video_output_path = output_base / "videos" / f"radio_{timestamp}.mp4"
    
    # 音声合成
    console.print("\n[bold]== 音声合成 ==[/bold]")
    synthesis_result = await voicevox.synthesize(script, audio_output_dir)
    
    # 動画生成
    console.print("\n[bold]== 動画生成 ==[/bold]")
    
    # アセットパスを解決
    background_image = PROJECT_ROOT / config.yaml.paths.background_image
    bgm_file = PROJECT_ROOT / config.yaml.paths.bgm_file
    
    # アセットの存在確認
    if not background_image.exists():
        console.print(f"[red]背景画像が見つかりません: {background_image}[/red]")
        console.print("[yellow]assets/backgrounds/default.png を配置してください。[/yellow]")
        return
    
    if not bgm_file.exists():
        console.print(f"[red]BGMファイルが見つかりません: {bgm_file}[/red]")
        console.print("[yellow]assets/bgm/default.mp3 を配置してください。[/yellow]")
        return
    
    render_result = await ffmpeg.render(
        synthesis_result=synthesis_result,
        background_image=background_image,
        bgm_file=bgm_file,
        output_path=video_output_path
    )
    
    # 台本をファイルに保存
    script_path = output_base / "script.json"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    
    # 完了メッセージ
    console.print("\n" + "=" * 50)
    console.print(Panel.fit(
        f"""[bold green]✓ 動画生成完了！[/bold green]

[bold]出力ファイル:[/bold]
  📹 動画: {render_result.video_path}
  📝 台本: {script_path}
  🎵 音声: {synthesis_result.audio_path}
  📄 字幕: {synthesis_result.subtitle_path}

[bold]動画情報:[/bold]
  ⏱️ 長さ: {render_result.duration_sec:.1f}秒
  📦 サイズ: {render_result.file_size_mb:.1f}MB
  🎬 タイトル: {script.title}""",
        title="完了",
        border_style="green"
    ))


if __name__ == "__main__":
    asyncio.run(main())
