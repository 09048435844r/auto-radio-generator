"""VOICEVOX APIを使用した音声合成クライアント"""
import asyncio
import shutil
import wave
from io import BytesIO
from pathlib import Path
from datetime import timedelta
from typing import Optional

import httpx
from pydub import AudioSegment
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from core.interfaces import IAudioSynthesizer, SynthesisResult, ChapterMarker
from core.models import Script, AppConfig

console = Console()


class VoicevoxClient(IAudioSynthesizer):
    """VOICEVOX Local APIを使用した音声合成
    
    ローカルで起動しているVOICEVOXエンジンに接続します。
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.base_url = config.env.voicevox_base_url
        self.speakers = config.yaml.audio_synthesizer.speakers
        self.audio_config = config.yaml.audio_synthesizer
    
    async def check_engine_status(self) -> bool:
        """VOICEVOXエンジンの状態を確認"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/version", timeout=5.0)
                if response.status_code == 200:
                    version = response.text.strip('"')
                    console.print(f"[green]✓ VOICEVOX エンジン接続成功[/green] v{version}")
                    return True
        except Exception as e:
            console.print(f"[red]✗ VOICEVOX エンジンに接続できません: {e}[/red]")
            console.print(f"[yellow]  → {self.base_url} でエンジンが起動しているか確認してください[/yellow]")
        return False
    
    async def synthesize(self, script: Script, output_dir: Path, speed_scale_override: Optional[float] = None) -> SynthesisResult:
        """台本から音声を合成
        
        Args:
            script: 台本データ
            output_dir: 出力ディレクトリ
            speed_scale_override: UIからの話速指定（優先される）
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Mock Mode Check
        mock_mode = self.config.yaml.dev.mock_mode if hasattr(self.config.yaml, 'dev') else False
        if mock_mode:
            mock_data_path = self.config.yaml.dev.mock_data_path if hasattr(self.config.yaml.dev, 'mock_data_path') else "tests/mock_data"
            mock_audio_file = Path(mock_data_path) / "audio" / "combined_audio.wav"
            mock_subtitle_file = Path(mock_data_path) / "audio" / "subtitles.ass"
            output_audio_path = output_dir / "combined_audio.wav"
            
            if mock_audio_file.exists():
                console.print(f"[yellow]⚠ MOCK MODE: Using audio from {mock_audio_file}[/yellow]")
                # Mockファイルを出力先にコピー
                shutil.copy(mock_audio_file, output_audio_path)
                
                # Mockファイルの情報を取得
                audio_segment = AudioSegment.from_wav(str(mock_audio_file))
                duration_sec = len(audio_segment) / 1000.0
                mock_chapters = self._build_mock_chapters(script, duration_sec)
                subtitle_path = output_dir / "subtitles.ass"

                if mock_subtitle_file.exists():
                    shutil.copy(mock_subtitle_file, subtitle_path)
                    console.print(f"[yellow]  ▶ Mock字幕をコピー: {mock_subtitle_file}[/yellow]")
                else:
                    mock_phrase_data = self._build_mock_phrase_data(script, duration_sec)
                    self._generate_ass(mock_phrase_data, subtitle_path)
                    console.print("[yellow]  ▶ Mock字幕を推定生成しました[/yellow]")
                
                console.print(f"[green]✓ Mock音声を使用しました[/green] ({duration_sec:.1f}秒)")
                console.print(f"[yellow]  ▶ Mockチャプター生成: {len(mock_chapters)}件[/yellow]")
                
                # SynthesisResultを返す（Mockでもチャプターを付与）
                return SynthesisResult(
                    audio_path=output_audio_path,
                    subtitle_path=subtitle_path,
                    total_duration_sec=duration_sec,  # 正しいフィールド名
                    chapters=mock_chapters
                )
            else:
                console.print(f"[red]✗ Mock audio not found at {mock_audio_file}[/red]")
                console.print(f"[yellow]  Falling back to normal VOICEVOX synthesis...[/yellow]")
        
        # UIからの指定がconfigより優先
        speed_scale = speed_scale_override if speed_scale_override is not None else self.audio_config.speed_scale
        
        # 一時ディレクトリ
        temp_dir = output_dir / "temp_phrases"
        temp_dir.mkdir(exist_ok=True)
        
        phrase_data = []  # (音声セグメント, 開始時間, 終了時間, テキスト, 話者ID)
        chapters: list[ChapterMarker] = []  # YouTubeチャプター情報
        current_time_ms = 0
        pause_ms = self.audio_config.pause_between_phrases_ms
        
        console.print(f"[cyan]音声合成中...[/cyan] {len(script.get_dialogue_only())} フレーズ")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("合成中...", total=len(script.get_dialogue_only()))
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                for i, line in enumerate(script.get_dialogue_only()):
                    # セクション開始を検出してチャプターを記録
                    # Note: 冒頭に2秒の無音が追加されるため、チャプタータイムスタンプを2秒オフセット
                    if line.section:
                        chapter_title = self._get_chapter_title(line.section, line.text, line.chapter_title)
                        pre_roll_offset_sec = 2.0  # 冒頭の無音時間（秒）
                        adjusted_time_sec = (current_time_ms / 1000.0) + pre_roll_offset_sec
                        chapters.append(ChapterMarker(
                            start_time_sec=adjusted_time_sec,
                            title=chapter_title,
                            section_id=line.section
                        ))
                        console.print(f"[yellow]  ▶ チャプター: {chapter_title} @ {adjusted_time_sec:.1f}s[/yellow]")
                    
                    # 話者IDからVOICEVOX speaker_idを取得
                    # line.speaker は "A" または "B"
                    voicevox_speaker_id = self.speakers.main if line.speaker == "A" else self.speakers.sub
                    
                    # デバッグ: 話者情報を表示
                    console.print(f"[dim]  [{i+1}] {line.speaker} → VOICEVOX ID: {voicevox_speaker_id}[/dim]")
                    
                    # 音声合成
                    audio_data = await self._synthesize_phrase(
                        client, line.text, voicevox_speaker_id, speed_scale
                    )
                    
                    # AudioSegmentに変換
                    audio_segment = AudioSegment.from_wav(BytesIO(audio_data))
                    duration_ms = len(audio_segment)
                    
                    # タイミング情報を記録（話者IDも含める）
                    start_time = current_time_ms
                    end_time = current_time_ms + duration_ms
                    phrase_data.append((audio_segment, start_time, end_time, line.text, line.speaker))
                    
                    current_time_ms = end_time + pause_ms
                    progress.update(task, advance=1, description=f"合成中... {i+1}/{len(script.get_dialogue_only())}")
        
        # 音声を結合
        console.print("[cyan]音声ファイルを結合中...[/cyan]")
        combined_audio = self._combine_audio(phrase_data, pause_ms)
        
        # 冒頭と末尾に無音を追加（演出強化）
        console.print("[cyan]冒頭・末尾に無音を追加中...[/cyan]")
        pre_roll = AudioSegment.silent(duration=2000)   # 冒頭2秒の無音
        post_roll = AudioSegment.silent(duration=5000)  # 末尾5秒の無音
        combined_audio = pre_roll + combined_audio + post_roll
        
        # 音声ファイルを保存
        audio_path = output_dir / "combined_audio.wav"
        combined_audio.export(str(audio_path), format="wav")
        
        # ASS字幕を生成（話者ごとに色分け）
        subtitle_path = output_dir / "subtitles.ass"
        self._generate_ass(phrase_data, subtitle_path)
        
        total_duration_sec = len(combined_audio) / 1000.0
        
        console.print(f"[green]✓ 音声合成完了[/green] 総時間: {total_duration_sec:.1f}秒")
        
        # 一時ファイルを削除
        for f in temp_dir.glob("*.wav"):
            f.unlink()
        temp_dir.rmdir()
        
        return SynthesisResult(
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            total_duration_sec=total_duration_sec,
            chapters=chapters
        )
    
    async def _synthesize_phrase(
        self,
        client: httpx.AsyncClient,
        text: str,
        speaker_id: int,
        speed_scale: float
    ) -> bytes:
        """１フレーズの音声を合成"""
        # 音声クエリを生成
        query_response = await client.post(
            f"{self.base_url}/audio_query",
            params={"text": text, "speaker": speaker_id}
        )
        query_response.raise_for_status()
        query = query_response.json()
        
        # 音声パラメータを設定（speed_scaleは引数から受け取る）
        query["speedScale"] = speed_scale
        query["pitchScale"] = self.audio_config.pitch_scale
        query["intonationScale"] = self.audio_config.intonation_scale
        query["volumeScale"] = self.audio_config.volume_scale
        
        # 音声を合成
        synthesis_response = await client.post(
            f"{self.base_url}/synthesis",
            params={"speaker": speaker_id},
            json=query
        )
        synthesis_response.raise_for_status()
        
        return synthesis_response.content
    
    def _combine_audio(
        self,
        phrase_data: list,
        pause_ms: int
    ) -> AudioSegment:
        """音声セグメントを結合"""
        if not phrase_data:
            return AudioSegment.silent(duration=1000)
        
        # 無音セグメント
        pause = AudioSegment.silent(duration=pause_ms)
        
        # 結合（話者ID追加に対応）
        combined = phrase_data[0][0]
        for item in phrase_data[1:]:
            segment = item[0]  # 最初の要素が音声セグメント
            combined += pause + segment
        
        return combined
    
    def _generate_ass(self, phrase_data: list, output_path: Path) -> None:
        """ASS形式の字幕ファイルを生成（話者ごとに色分け）
        
        Note: 冒頭に2秒の無音が追加されているため、字幕タイミングを2秒オフセット
        """
        pre_roll_offset_ms = 2000  # 冒頭の無音時間
        
        # ASSヘッダー
        header = """[Script Info]
Title: Auto Radio Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Meiryo,105,&H0055FF55,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,6,2,2,20,20,30,1
Style: Sub,Meiryo,105,&H00FFFFFF,&H000000FF,&H00CC99FF,&H80000000,0,0,0,0,100,100,0,0,1,6,2,2,20,20,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        lines = [header]
        
        for _, start_ms, end_ms, text, speaker in phrase_data:
            # 冒頭の無音分をオフセット
            adjusted_start_ms = start_ms + pre_roll_offset_ms
            adjusted_end_ms = end_ms + pre_roll_offset_ms
            
            start_time = self._ms_to_ass_time(adjusted_start_ms)
            end_time = self._ms_to_ass_time(adjusted_end_ms)
            
            # 話者IDに応じてスタイルを選択
            style = "Main" if speaker == "A" else "Sub"
            
            # BudouXで自然な改行位置を取得（限界設定: 画面端ギリギリまで拡大）
            from budoux import load_default_japanese_parser
            parser = load_default_japanese_parser()
            chunks = parser.parse(text)
            wrapped_text = self._wrap_subtitle_budoux(chunks, max_chars=28)
            
            lines.append(f"Dialogue: 0,{start_time},{end_time},{style},,0,0,0,,{wrapped_text}\n")
        
        output_path.write_text("".join(lines), encoding="utf-8")
    
    @staticmethod
    def _wrap_subtitle_budoux(chunks: list[str], max_chars: int = 28) -> str:
        """文節区切りされたチャンクを指定文字数で折り返す
        
        Args:
            chunks: BudouXで分割された文節リスト
            max_chars: 1行あたりの最大文字数
        
        Returns:
            str: ASS形式の改行コード（\\N）で区切られたテキスト
        """
        lines = []
        current_line = ""
        
        for chunk in chunks:
            test_line = current_line + chunk
            if len(test_line) <= max_chars or not current_line:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = chunk
        
        if current_line:
            lines.append(current_line)
        
        return "\\N".join(lines)
    
    @staticmethod
    def _ms_to_ass_time(ms: int) -> str:
        """ミリ秒をASS形式の時間文字列に変換"""
        td = timedelta(milliseconds=ms)
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        centiseconds = (ms % 1000) // 10
        return f"{hours:01d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

    def _build_mock_chapters(self, script: Script, total_duration_sec: float) -> list[ChapterMarker]:
        """Mockモード用に台本のsection情報からチャプター時刻を推定する"""
        dialogue = script.get_dialogue_only()
        if not dialogue:
            return []

        pre_roll_offset_sec = 2.0
        total_lines = len(dialogue)
        timeline_span_sec = max(1.0, float(total_duration_sec) - pre_roll_offset_sec)
        mock_chapters: list[ChapterMarker] = []

        for index, line in enumerate(dialogue):
            if not line.section:
                continue

            chapter_title = self._get_chapter_title(line.section, line.text, line.chapter_title)
            position_ratio = index / max(1, total_lines - 1)
            estimated_start = pre_roll_offset_sec + (timeline_span_sec * position_ratio)
            estimated_start = min(max(0.0, estimated_start), max(0.0, total_duration_sec - 0.1))

            mock_chapters.append(
                ChapterMarker(
                    start_time_sec=estimated_start,
                    title=chapter_title,
                    section_id=line.section,
                )
            )

        return mock_chapters

    def _build_mock_phrase_data(self, script: Script, total_duration_sec: float) -> list[tuple]:
        """Mockモード用にASS字幕生成のための擬似タイミングを作成する"""
        dialogue = script.get_dialogue_only()
        if not dialogue:
            return []

        pre_roll_ms = 2000
        post_roll_ms = 5000
        total_ms = max(1000, int(total_duration_sec * 1000))
        timeline_ms = max(1000, total_ms - pre_roll_ms - post_roll_ms)
        total_weight = sum(max(1, len((line.text or "").strip())) for line in dialogue)

        phrase_data: list[tuple] = []
        current_ms = 0
        pause_ms = 250

        for idx, line in enumerate(dialogue):
            remaining_weight = sum(
                max(1, len((item.text or "").strip())) for item in dialogue[idx:]
            )
            if idx == len(dialogue) - 1:
                duration_ms = max(600, timeline_ms - current_ms)
            else:
                weight = max(1, len((line.text or "").strip()))
                duration_ms = max(600, int((timeline_ms * weight) / max(1, total_weight)))
                max_allowed = max(600, timeline_ms - current_ms - (len(dialogue) - idx - 1) * 600)
                duration_ms = min(duration_ms, max_allowed)

            start_ms = max(0, current_ms)
            end_ms = min(timeline_ms, start_ms + duration_ms)
            if end_ms <= start_ms:
                end_ms = min(timeline_ms, start_ms + 600)

            phrase_data.append(
                (
                    AudioSegment.silent(duration=max(1, end_ms - start_ms)),
                    start_ms,
                    end_ms,
                    line.text,
                    line.speaker,
                )
            )

            current_ms = end_ms + pause_ms
            if current_ms >= timeline_ms:
                break

        return phrase_data
    
    def _get_chapter_title(self, section_id: str, text: str, chapter_title: Optional[str] = None) -> str:
        """セクションIDからチャプタータイトルを生成
        
        Args:
            section_id: セクションID (例: 'intro', 'news_1')
            text: セリフテキスト
            chapter_title: AI生成のチャプタータイトル（優先使用）
        
        Returns:
            チャプタータイトル文字列
        """
        # 優先度1: AI生成のchapter_titleがあれば使用
        if chapter_title and chapter_title.strip():
            return chapter_title.strip()
        
        # 優先度2: 固定マッピングにフォールバック（後方互換性のため）
        section_titles = {
            "intro": "オープニング",
            "definition": "基礎解説",
            "metaphor": "たとえで理解",
            "example": "活用例",
            "main": "本題",
            "news_1": "ニュース1",
            "news_2": "ニュース2",
            "news_3": "ニュース3",
            "listener_mail": "リスナーメール",
            "ending": "エンディング",
        }
        
        base_title = section_titles.get(section_id, section_id)
        
        # news_N の場合、セリフから見出しを抽出（最初の30文字まで）
        if section_id.startswith("news_"):
            headline = text[:30].replace('\n', ' ')
            if len(text) > 30:
                headline += "..."
            return f"{base_title}: {headline}"
        
        return base_title
