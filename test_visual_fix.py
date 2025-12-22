"""視覚的修正の検証用スクリプト

字幕の自動折り返しとスペクトラム視認性向上の修正を検証するため、
冒頭10秒程度のテスト動画を生成します。
"""
import sys
from pathlib import Path
from datetime import datetime

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import load_config
from core.interfaces import SynthesisResult
from services.video_rendering import FfmpegRenderer
from services.audio_synthesis import VoicevoxClient
from pydub import AudioSegment
from rich.console import Console

console = Console()


def find_latest_output() -> Path | None:
    """最新の出力ディレクトリを検索"""
    output_dir = PROJECT_ROOT / "output"
    if not output_dir.exists():
        return None
    
    dirs = sorted([d for d in output_dir.iterdir() if d.is_dir()], reverse=True)
    
    # audio/combined_audio.wav が存在するディレクトリを探す
    for d in dirs:
        audio_file = d / "audio" / "combined_audio.wav"
        if audio_file.exists():
            return d
    
    return None


def create_test_subtitle(output_path: Path) -> None:
    """テスト用のASS字幕を生成（長文を含む）"""
    
    # 長文テストケース
    test_dialogues = [
        (0, 3000, "これは短いテストです。", "main"),
        (3000, 8000, "これは非常に長いテキストで、画面の端まで到達してしまう可能性があるため、自動折り返し機能が正しく動作するかを確認するためのテストケースです。", "sub"),
        (8000, 12000, "折り返しが正しく機能していれば、この文章も適切に表示されるはずです。", "main"),
    ]
    
    header = """[Script Info]
Title: Test Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Meiryo,48,&H0055FF55,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,2,2,10,10,30,1
Style: Sub,Meiryo,48,&H00FFFFFF,&H000000FF,&H00CC99FF,&H80000000,0,0,0,0,100,100,0,0,1,3,2,2,10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    lines = [header]
    
    # textwrapを使用して折り返し処理をテスト
    import textwrap
    
    for start_ms, end_ms, text, speaker_id in test_dialogues:
        start_time = ms_to_ass_time(start_ms)
        end_time = ms_to_ass_time(end_ms)
        style = "Main" if speaker_id == "main" else "Sub"
        
        # 自動折り返し（修正後のロジックと同じ）
        wrapped_text = "\\N".join(textwrap.wrap(text, width=25))
        
        lines.append(f"Dialogue: 0,{start_time},{end_time},{style},,0,0,0,,{wrapped_text}\n")
    
    output_path.write_text("".join(lines), encoding="utf-8")
    console.print(f"[green]OK テスト字幕生成完了:[/green] {output_path}")


def ms_to_ass_time(ms: int) -> str:
    """ミリ秒をASS形式の時間文字列に変換"""
    from datetime import timedelta
    td = timedelta(milliseconds=ms)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    centiseconds = (ms % 1000) // 10
    return f"{hours:01d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def create_test_audio(output_path: Path, duration_sec: float = 12.0) -> None:
    """テスト用の音声を生成（440Hzのトーン + 無音）"""
    from pydub.generators import Sine
    
    # 440Hz (A4) のトーンを3秒
    tone = Sine(440).to_audio_segment(duration=3000)
    
    # 無音を追加して合計12秒に
    silence = AudioSegment.silent(duration=int((duration_sec - 3.0) * 1000))
    
    combined = tone + silence
    combined.export(output_path, format="wav")
    console.print(f"[green]OK テスト音声生成完了:[/green] {output_path} ({duration_sec}秒)")


def main():
    console.print("[bold cyan]========================================[/bold cyan]")
    console.print("[bold cyan]視覚的修正の検証テスト[/bold cyan]")
    console.print("[bold cyan]========================================[/bold cyan]\n")
    
    # 設定読み込み
    config = load_config()
    
    # テスト用ディレクトリ
    test_dir = PROJECT_ROOT / "output" / "test_visual_fix"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    audio_dir = test_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    
    # 1. 音声ファイルの準備
    console.print("[cyan]== Step 1: 音声ファイルの準備 ==[/cyan]")
    latest_output = find_latest_output()
    
    if latest_output:
        source_audio = latest_output / "audio" / "combined_audio.wav"
        console.print(f"既存の音声を使用: {source_audio}")
        
        # 冒頭12秒のみを切り出し
        audio = AudioSegment.from_wav(source_audio)
        audio_12sec = audio[:12000]  # 12秒
        
        test_audio_path = audio_dir / "test_audio.wav"
        audio_12sec.export(test_audio_path, format="wav")
        console.print(f"[green]OK 音声を12秒に切り出し:[/green] {test_audio_path}")
    else:
        console.print("[yellow]既存の音声が見つかりません。テスト用音声を生成します。[/yellow]")
        test_audio_path = audio_dir / "test_audio.wav"
        create_test_audio(test_audio_path, duration_sec=12.0)
    
    # 2. 字幕ファイルの生成
    console.print("\n[cyan]== Step 2: テスト字幕の生成 ==[/cyan]")
    test_subtitle_path = audio_dir / "test_subtitles.ass"
    create_test_subtitle(test_subtitle_path)
    
    # 字幕内容をログ出力
    console.print("\n[yellow]生成された字幕内容（折り返し処理確認）:[/yellow]")
    subtitle_content = test_subtitle_path.read_text(encoding="utf-8")
    for line in subtitle_content.split("\n"):
        if line.startswith("Dialogue:"):
            console.print(f"  {line}")
    
    # 3. 背景画像の準備
    console.print("\n[cyan]== Step 3: 背景画像の準備 ==[/cyan]")
    bg_images = list((PROJECT_ROOT / "assets" / "backgrounds").glob("*.png"))
    if bg_images:
        background_image = bg_images[0]
        console.print(f"背景画像: {background_image.name}")
    else:
        console.print("[red]背景画像が見つかりません。[/red]")
        return
    
    # 4. BGM準備
    console.print("\n[cyan]== Step 4: BGMの準備 ==[/cyan]")
    bgm_files = list((PROJECT_ROOT / "assets" / "bgm").glob("*.mp3"))
    if bgm_files:
        bgm_file = bgm_files[0]
        console.print(f"BGM: {bgm_file.name}")
    else:
        console.print("[yellow]BGMが見つかりません。BGMなしで生成します。[/yellow]")
        bgm_file = None
    
    # 5. 動画レンダリング
    console.print("\n[cyan]== Step 5: テスト動画のレンダリング ==[/cyan]")
    console.print("[yellow]スペクトラム表示: 有効（白色、太い線）[/yellow]")
    console.print("[yellow]動画時間: 12秒[/yellow]\n")
    
    renderer = FfmpegRenderer(config)
    
    test_video_path = test_dir / "test_video.mp4"
    
    # SynthesisResultを作成（FfmpegRenderer.renderの引数に合わせる）
    synthesis_result = SynthesisResult(
        audio_path=test_audio_path,
        subtitle_path=test_subtitle_path,
        total_duration_sec=12.0,
        chapters=[]
    )
    
    try:
        import asyncio
        result = asyncio.run(renderer.render(
            synthesis_result=synthesis_result,
            background_image=background_image,
            bgm_file=bgm_file,
            output_path=test_video_path
        ))
        
        console.print(f"\n[bold green]OK テスト動画生成完了![/bold green]")
        console.print(f"  出力先: {result.video_path}")
        console.print(f"  ファイルサイズ: {result.file_size_mb:.2f} MB")
        console.print(f"  動画時間: {result.duration_sec:.1f}秒")
        
        console.print("\n[bold cyan]========================================[/bold cyan]")
        console.print("[bold yellow]検証項目:[/bold yellow]")
        console.print("  1. 字幕が画面端で切れずに折り返されているか？")
        console.print("  2. スペクトラムが白い太い線で視認できるか？")
        console.print("[bold cyan]========================================[/bold cyan]")
        
    except Exception as e:
        console.print(f"\n[bold red]ERROR エラーが発生しました:[/bold red] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
