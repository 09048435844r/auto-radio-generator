"""設定モデル（Pydantic）"""
import os
from pathlib import Path
from typing import Literal, Dict, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# =============================================================================
# 環境変数設定 (.env)
# =============================================================================
class EnvSettings(BaseSettings):
    """環境変数から読み込む設定"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    perplexity_api_key: str = Field(default="", alias="PERPLEXITY_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    voicevox_base_url: str = Field(
        default="http://localhost:50021",
        alias="VOICEVOX_BASE_URL"
    )


# =============================================================================
# YAML設定モデル (config.yaml)
# =============================================================================

# リサーチモード設定
class ResearchModeConfig(BaseModel):
    """リサーチモードの設定"""
    name: str
    description: str
    system_prompt: str


class ResearcherConfig(BaseModel):
    """リサーチャー（Perplexity）設定"""
    model: str = "sonar-pro"
    max_tokens: int = 2048
    modes: Dict[str, ResearchModeConfig] = Field(default_factory=dict)


# 台本生成設定
class GeminiConfig(BaseModel):
    """Gemini API設定"""
    model: str = "gemini-2.0-flash"
    fallback_model: str = "gemini-1.5-flash"
    max_tokens: int = 8192


class ScriptStructureConfig(BaseModel):
    """台本構成比率"""
    main_topic_ratio: int = 70
    listener_mail_ratio: int = 20
    ending_ratio: int = 10


class ScriptGeneratorConfig(BaseModel):
    """台本生成エンジン設定"""
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    structure: ScriptStructureConfig = Field(default_factory=ScriptStructureConfig)


class SpeakersConfig(BaseModel):
    """話者ID設定"""
    main: int = 3  # ずんだもん
    sub: int = 1   # 四国めたん


class AudioSynthesizerConfig(BaseModel):
    """音声合成設定"""
    speakers: SpeakersConfig = Field(default_factory=SpeakersConfig)
    speed_scale: float = 1.0
    pitch_scale: float = 0.0
    intonation_scale: float = 1.0
    volume_scale: float = 1.0
    pause_between_phrases_ms: int = 500


class VideoRendererConfig(BaseModel):
    """動画生成設定"""
    output_resolution: str = "1920x1080"
    output_fps: int = 30
    output_codec: str = "libx264"
    output_audio_codec: str = "aac"
    output_audio_bitrate: str = "192k"
    bgm_volume: float = 0.15
    bgm_fade_in_sec: float = 3.0
    bgm_fade_out_sec: float = 3.0
    # スペクトラム可視化設定
    enable_spectrum: bool = True
    spectrum_color: str = "0x00FF88"
    spectrum_mode: str = "cline"


class PathsConfig(BaseModel):
    """パス設定"""
    assets_dir: str = "assets"
    output_dir: str = "output"
    background_image: str = "assets/backgrounds/default.png"
    bgm_file: str = "assets/bgm/default.mp3"


class PersonalityConfig(BaseModel):
    """パーソナリティ設定"""
    name: str
    description: str


class PersonalitiesConfig(BaseModel):
    """パーソナリティ一覧"""
    main: PersonalityConfig = Field(
        default_factory=lambda: PersonalityConfig(
            name="ずんだもん",
            description="元気で明るいメインパーソナリティ。語尾に「なのだ」をつける。"
        )
    )
    sub: PersonalityConfig = Field(
        default_factory=lambda: PersonalityConfig(
            name="めたん",
            description="落ち着いた雰囲気のアシスタント。丁寧な言葉遣い。"
        )
    )


class YamlConfig(BaseModel):
    """YAML設定ファイル全体"""
    researcher: ResearcherConfig = Field(default_factory=ResearcherConfig)
    script_generator: ScriptGeneratorConfig = Field(
        default_factory=ScriptGeneratorConfig
    )
    audio_synthesizer: AudioSynthesizerConfig = Field(
        default_factory=AudioSynthesizerConfig
    )
    video_renderer: VideoRendererConfig = Field(
        default_factory=VideoRendererConfig
    )
    paths: PathsConfig = Field(default_factory=PathsConfig)
    personalities: PersonalitiesConfig = Field(default_factory=PersonalitiesConfig)


# =============================================================================
# 統合設定クラス
# =============================================================================
class AppConfig(BaseModel):
    """アプリケーション全体の設定"""
    env: EnvSettings
    yaml: YamlConfig
    project_root: Path

    class Config:
        arbitrary_types_allowed = True


def load_config(
    project_root: Path | str | None = None,
    config_file: str = "config.yaml"
) -> AppConfig:
    """設定を読み込む
    
    Args:
        project_root: プロジェクトルートディレクトリ
        config_file: YAML設定ファイル名
    
    Returns:
        AppConfig: 統合設定オブジェクト
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent
    else:
        project_root = Path(project_root)
    
    # .envファイルのパスを設定
    env_file = project_root / ".env"
    if env_file.exists():
        os.environ.setdefault("ENV_FILE", str(env_file))
    
    # 環境変数を読み込み
    env_settings = EnvSettings(_env_file=env_file if env_file.exists() else None)
    
    # YAML設定を読み込み
    yaml_path = project_root / config_file
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
        yaml_config = YamlConfig.model_validate(yaml_data)
    else:
        yaml_config = YamlConfig()
    
    return AppConfig(
        env=env_settings,
        yaml=yaml_config,
        project_root=project_root
    )
