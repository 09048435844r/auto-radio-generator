"""ユーザー設定の永続化管理

前回の設定を保存し、次回起動時に復元する機能を提供します。
"""
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


@dataclass
class UserSettings:
    """ユーザー設定"""
    # リサーチ設定
    research_mode: str = "トリビア (雑学)"
    
    # 素材設定
    background_image: Optional[str] = None
    bgm_file: Optional[str] = None
    
    # 動画設定
    bgm_volume: float = 0.15
    fade_time: float = 3.0
    speed_scale: float = 1.1
    enable_spectrum: bool = True
    
    def to_dict(self) -> dict:
        """辞書に変換"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "UserSettings":
        """辞書から復元"""
        return cls(**data)


class SettingsManager:
    """設定管理クラス"""
    
    def __init__(self, settings_path: Optional[Path] = None):
        """初期化
        
        Args:
            settings_path: 設定ファイルのパス（デフォルト: user_settings.json）
        """
        if settings_path is None:
            # プロジェクトルートに保存
            project_root = Path(__file__).parent.parent
            settings_path = project_root / "user_settings.json"
        
        self.settings_path = settings_path
    
    def load(self) -> UserSettings:
        """設定を読み込む
        
        Returns:
            UserSettings: 読み込んだ設定（ファイルがない場合はデフォルト値）
        """
        if not self.settings_path.exists():
            return UserSettings()
        
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return UserSettings.from_dict(data)
        except Exception as e:
            print(f"[WARNING] 設定ファイルの読み込みに失敗しました: {e}")
            return UserSettings()
    
    def save(self, settings: UserSettings):
        """設定を保存
        
        Args:
            settings: 保存する設定
        """
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARNING] 設定ファイルの保存に失敗しました: {e}")
    
    def update_from_ui(
        self,
        research_mode: str,
        background_image: Optional[str],
        bgm_file: Optional[str],
        bgm_volume: float,
        fade_time: float,
        speed_scale: float,
        enable_spectrum: bool
    ):
        """UI入力から設定を更新して保存
        
        Args:
            research_mode: リサーチモード
            background_image: 背景画像ファイル名
            bgm_file: BGMファイル名
            bgm_volume: BGM音量
            fade_time: フェード時間
            speed_scale: 話速
            enable_spectrum: スペクトラム表示
        """
        settings = UserSettings(
            research_mode=research_mode,
            background_image=background_image,
            bgm_file=bgm_file,
            bgm_volume=bgm_volume,
            fade_time=fade_time,
            speed_scale=speed_scale,
            enable_spectrum=enable_spectrum
        )
        self.save(settings)
