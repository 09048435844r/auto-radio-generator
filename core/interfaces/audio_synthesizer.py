"""音声合成インターフェース"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.models import Script, AppConfig


@dataclass
class ChapterMarker:
    """YouTubeチャプター用のマーカー"""
    start_time_sec: float     # 開始時間（秒）
    title: str                # チャプタータイトル
    section_id: str           # セクションID（例: 'intro', 'news_1'）


@dataclass
class SynthesisResult:
    """音声合成の結果"""
    audio_path: Path          # 結合された音声ファイルパス
    subtitle_path: Path       # SRT字幕ファイルパス
    total_duration_sec: float # 総再生時間（秒）
    chapters: list[ChapterMarker] = field(default_factory=list)  # YouTubeチャプター情報


class IAudioSynthesizer(ABC):
    """音声合成の抽象インターフェース
    
    将来的なエンジン変更（ElevenLabs, Azure TTS等）に備えて
    抽象クラスとして定義。
    """
    
    def __init__(self, config: AppConfig):
        """
        Args:
            config: アプリケーション設定
        """
        self.config = config
    
    @abstractmethod
    async def synthesize(self, script: Script, output_dir: Path) -> SynthesisResult:
        """台本から音声を合成する
        
        Args:
            script: 台本データ
            output_dir: 出力ディレクトリ
        
        Returns:
            SynthesisResult: 合成結果（音声パス、字幕パス、総時間）
        
        Raises:
            AudioSynthesisError: 合成に失敗した場合
        """
        pass
    
    @abstractmethod
    async def check_engine_status(self) -> bool:
        """音声合成エンジンの状態を確認する
        
        Returns:
            bool: エンジンが利用可能な場合True
        """
        pass
