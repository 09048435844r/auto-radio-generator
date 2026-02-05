"""FFmpegを使用した動画レンダリング"""
import asyncio
import subprocess
import shutil
import os
from datetime import datetime
from pathlib import Path

from rich.console import Console

from core.interfaces import IVideoRenderer, RenderResult, SynthesisResult
from core.models import AppConfig

console = Console()


class FfmpegRenderer(IVideoRenderer):
    """FFmpegを使用した動画生成
    
    背景画像、音声、BGM、字幕を合成してMP4動画を生成します。
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.video_config = config.yaml.video_renderer
        
        # FFmpegのパス（環境変数PATH、またはプロジェクト内のffmpeg.exe）
        self.ffmpeg_path = self._find_ffmpeg()
    
    def _find_ffmpeg(self) -> str:
        """FFmpegの実行パスを探す"""
        # まずプロジェクトルートを確認
        project_ffmpeg = self.config.project_root.parent / "ffmpeg.exe"
        if project_ffmpeg.exists():
            return str(project_ffmpeg)
        
        # PATHから探す
        ffmpeg_in_path = shutil.which("ffmpeg")
        if ffmpeg_in_path:
            return ffmpeg_in_path
        
        # デフォルト
        return "ffmpeg"
    
    def check_ffmpeg_available(self) -> bool:
        """FFmpegが利用可能か確認"""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # バージョン情報の最初の行を取得
                version_line = result.stdout.split('\n')[0]
                console.print(f"[green]OK FFmpeg 利用可能[/green] {version_line}")
                return True
        except Exception as e:
            console.print(f"[red]ERROR FFmpeg が見つかりません: {e}[/red]")
        return False
    
    async def render(
        self,
        synthesis_result: SynthesisResult,
        background_image: Path,
        bgm_file: Path,
        output_path: Path,
        subtitle_path: Path | None = None
    ) -> RenderResult:
        """動画を生成
        
        Args:
            synthesis_result: 音声合成の結果
            background_image: 背景画像パス
            bgm_file: BGMファイルパス
            output_path: 出力動画パス
            subtitle_path: 字幕ファイルパス（オプショナル、明示的に指定されない場合はsynthesis_resultから取得）
        """
        console.print("[cyan]動画を生成中...[/cyan]")
        
        # 出力ディレクトリを確保
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 字幕パスの決定：明示的に指定された場合はそれを優先、そうでなければsynthesis_resultから取得
        final_subtitle_path = subtitle_path if subtitle_path is not None else synthesis_result.subtitle_path
        
        # 設定値
        resolution = self.video_config.output_resolution
        fps = self.video_config.output_fps
        bgm_volume = self.video_config.bgm_volume
        fade_in = self.video_config.bgm_fade_in_sec
        fade_out = self.video_config.bgm_fade_out_sec
        total_duration = synthesis_result.total_duration_sec
        
        # FFmpegコマンドを構築
        cmd = self._build_ffmpeg_command(
            background_image=background_image,
            audio_file=synthesis_result.audio_path,
            bgm_file=bgm_file,
            subtitle_file=final_subtitle_path,
            output_path=output_path,
            resolution=resolution,
            fps=fps,
            bgm_volume=bgm_volume,
            fade_in_sec=fade_in,
            fade_out_sec=fade_out,
            total_duration_sec=total_duration
        )
        
        console.print(f"[dim]実行コマンド: {' '.join(cmd[:10])}...[/dim]")
        
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
    
    def _build_ffmpeg_command(
        self,
        background_image: Path,
        audio_file: Path,
        bgm_file: Path,
        subtitle_file: Path,
        output_path: Path,
        resolution: str,
        fps: int,
        bgm_volume: float,
        fade_in_sec: float,
        fade_out_sec: float,
        total_duration_sec: float
    ) -> list[str]:
        """FFmpegコマンドを構築"""
        width, height = resolution.split('x')
        
        # BGMフェードアウト開始時間
        fade_out_start = max(0, total_duration_sec - fade_out_sec)
        
        # スペクトラム設定
        enable_spectrum = self.video_config.enable_spectrum
        spectrum_color = self.video_config.spectrum_color
        spectrum_mode = self.video_config.spectrum_mode
        
        # フィルター複合構築
        # BGM: ループ再生、音量調整、フェードイン/アウト
        bgm_filter = (
            f"[2:a]volume={bgm_volume},"
            f"afade=t=in:st=0:d={fade_in_sec},"
            f"afade=t=out:st={fade_out_start}:d={fade_out_sec}[bgm]"
        )
        
        # 音声ミックス
        audio_mix_filter = "[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        
        # 字幕ファイル (.ass) の適用
        if subtitle_file and subtitle_file.exists():
            # 【重要】Windows絶対パスのトラブル回避策
            # カレントディレクトリ(プロジェクトルート)からの相対パスに変換する
            # 例: E:\project\output\...\subs.ass -> output/2025.../subs.ass
            try:
                rel_path = os.path.relpath(subtitle_file, os.getcwd())
                # パス区切りをスラッシュに統一 (Windowsの \ はFFmpegでエスケープ問題を起こすため)
                safe_path = rel_path.replace("\\", "/")
            except ValueError:
                # 万が一別ドライブの場合は、やむを得ず絶対パスを使い、コロンだけエスケープする
                safe_path = str(subtitle_file.resolve()).replace("\\", "/").replace(":", "\\:")

            console.print(f"[dim]DEBUG: Using subtitle path for FFmpeg: {safe_path}[/dim]")
            
            # フィルタの書き方を 'subtitles=filename' に統一（assフィルタのエイリアスだがこちらが安定）
            # ファイル名をシングルクォートで囲む
            subtitle_filter = f"subtitles='{safe_path}'"
        else:
            console.print("[yellow]WARNING: Subtitle path not provided or file not found.[/yellow]")
            subtitle_filter = None
        
        # 日付表示フィルター（右上に透かし文字で表示）
        creation_date = datetime.now().strftime("%Y/%m/%d")
        # drawtextフィルター: Windowsの場合はフォントファイルを直接指定
        # C:/Windows/Fonts/arial.ttf を使用してFontconfigエラーを回避
        date_filter = (
            f"drawtext=text='{creation_date}':"
            f"fontfile='C\\:/Windows/Fonts/arial.ttf':"
            f"fontsize=28:fontcolor=white@0.7:"
            f"x=w-tw-20:y=20:"
            f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
        )
        
        # ビデオフィルター構築
        if enable_spectrum:
            # 音声波形ビジュアライザーを追加
            # showwaves: 波形表示、画面上部1/3付近に配置（字幕との被りを防ぐ）
            spectrum_height = int(int(height) * 0.12)  # 画面高さの12%
            spectrum_y = int(int(height) * 0.25)  # 画面上部25%の位置（上部1/3付近）
            
            # 波形生成フィルター（視認性向上: 太い線、明るい色）
            waves_filter = (
                f"[1:a]showwaves=s={width}x{spectrum_height}:"
                f"mode=line:colors=white:"
                f"rate={fps}:scale=lin[waves]"
            )
            
            # 背景画像スケーリング
            bg_scale_filter = f"[0:v]scale={width}:{height}[bg]"
            
            # 波形を背景にオーバーレイ
            overlay_filter = f"[bg][waves]overlay=0:{spectrum_y}:format=auto[composed]"
            
            # 日付と字幕を合成
            if subtitle_filter:
                video_filter = f"{waves_filter};{bg_scale_filter};{overlay_filter};[composed]{date_filter},{subtitle_filter}[vout]"
            else:
                video_filter = f"{waves_filter};{bg_scale_filter};{overlay_filter};[composed]{date_filter}[vout]"
        else:
            # スペクトラムなし（日付と字幕のみ）
            if subtitle_filter:
                video_filter = f"[0:v]scale={width}:{height},{date_filter},{subtitle_filter}[vout]"
            else:
                video_filter = f"[0:v]scale={width}:{height},{date_filter}[vout]"
        
        # フィルター全体
        filter_complex = f"{bgm_filter};{audio_mix_filter};{video_filter}"
        
        # GPU加速設定の取得
        use_gpu = getattr(self.video_config, 'use_gpu', False)
        
        # エンコーダー設定を切り替え
        if use_gpu:
            # GPU加速（NVENC）を使用
            console.print("[green]🚀 Using GPU Acceleration (RTX 4070/NVENC)[/green]")
            video_codec = "h264_nvenc"
            codec_params = [
                "-preset", "p4",      # RTXシリーズ向け推奨プリセット
                "-rc", "vbr",         # 可変ビットレート
                "-cq", "23",          # Constant Quality (23 = 高品質)
                "-b:v", "0",          # ビットレート制限なし（CQ優先）
            ]
        else:
            # CPU エンコーディング（libx264）
            console.print("[yellow]🐢 Using CPU Encoding (libx264)[/yellow]")
            video_codec = "libx264"
            codec_params = [
                "-preset", "medium",  # CPUプリセット
                "-crf", "23",         # Constant Rate Factor
            ]
        
        cmd = [
            self.ffmpeg_path,
            "-y",  # 上書き確認なし
            
            # 入力1: 背景画像（ループ）
            "-loop", "1",
            "-i", str(background_image),
            
            # 入力2: メイン音声
            "-i", str(audio_file),
            
            # 入力3: BGM（無限ループ）
            "-stream_loop", "-1",
            "-i", str(bgm_file),
            
            # フィルター
            "-filter_complex", filter_complex,
            
            # 出力マッピング
            "-map", "[vout]",
            "-map", "[aout]",
            
            # ビデオコーデック設定（GPU/CPU切り替え）
            "-c:v", video_codec,
            *codec_params,  # プリセットと品質設定を展開
            "-r", str(fps),
            "-pix_fmt", "yuv420p",  # 互換性のため必須
            
            # オーディオコーデック設定
            "-c:a", self.video_config.output_audio_codec,
            "-b:a", self.video_config.output_audio_bitrate,
            
            # 音声トラック終了で停止
            "-shortest",
            
            # 出力ファイル
            str(output_path)
        ]
        
        return cmd
