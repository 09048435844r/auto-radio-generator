"""設定モデル（Pydantic）"""
import os
from pathlib import Path
from typing import Literal, Dict, Optional, List

import yaml
from pydantic import BaseModel, Field, model_validator
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
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
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
    max_queries_per_plan: int = 3
    max_requests_per_workflow: int = 6
    enable_session_cache: bool = True
    modes: Dict[str, ResearchModeConfig] = Field(default_factory=dict)


# 台本生成設定
class ModelCost(BaseModel):
    """モデルのコスト情報（USD per 1M tokens）"""
    input: float
    output: float


class GeminiConfig(BaseModel):
    """Gemini API設定"""
    model: str = "gemini-3.1-pro-preview"
    fallback_model: str = "gemini-2.5-pro"
    flash_model: str = "gemini-2.5-flash"  # 軽量モデル（サムネイル再作成用）
    max_tokens: int = 8192
    costs: Dict[str, ModelCost] = Field(default_factory=dict)


class OpenAIConfig(BaseModel):
    """OpenAI API設定"""
    model: str = "gpt-4o-mini"
    fallback_model: str = "gpt-4o"
    max_tokens: int = 8192
    temperature: float = 0.85
    costs: Dict[str, ModelCost] = Field(default_factory=dict)


class AnthropicConfig(BaseModel):
    """Anthropic API設定"""
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    temperature: float = 0.85
    costs: Dict[str, ModelCost] = Field(default_factory=dict)


class OllamaConfig(BaseModel):
    """Ollama（ローカルLLM）設定"""
    model: str = "gpt-oss:20b-long"
    base_url: str = "http://192.168.0.73:11434/v1"  # Production: Mac server IP
    max_tokens: int = 16384  # Increased for long-form content
    temperature: float = 0.85
    costs: Dict[str, ModelCost] = Field(default_factory=dict)


class ScriptStructureConfig(BaseModel):
    """台本構成比率"""
    main_topic_ratio: int = 70
    listener_mail_ratio: int = 20
    ending_ratio: int = 10


class CurrencyConfig(BaseModel):
    """通貨換算設定"""
    usd_to_jpy: float = 150.0


class OrchestratorSegmentConfig(BaseModel):
    """オーケストレーターのセグメント設定"""
    min_turns: int = 10
    max_turns: int = 20


class OrchestratorConfig(BaseModel):
    """Hierarchical Agentic Workflow オーケストレーター設定"""
    
    # Direct Regex Bypass: Phase 2 JSON変換をスキップするプロバイダー
    # ローカルLLMはJSON構造化が不安定なため、正規表現パーサーを優先
    LOCAL_LLM_PROVIDERS: set[str] = {"ollama", "lmstudio", "localai"}
    
    enabled: bool = Field(default=False, description="Trueにすると新アーキテクチャを使用")
    two_phase_generation: bool = Field(
        default=False,
        description="Trueにすると2段階生成（Markdown→JSON）を使用"
    )
    curator_model: str = Field(
        default="gemini-2.5-flash",
        description="キュレーション・要約用軽量モデル"
    )
    segment_model: str = Field(
        default="",
        description="Phase 1（クリエイティブ生成）用モデル（空の場合はデフォルトモデルを使用）"
    )
    json_model: str = Field(
        default="",
        description="Phase 2（JSON構造化）専用モデル（空の場合はsegment_modelと同じ）"
    )
    max_topics: int = Field(default=3, description="キュレーションで選定する最大トピック数")
    context_summary_max_length: int = Field(
        default=300, description="文脈要約の最大文字数"
    )
    intro: OrchestratorSegmentConfig = Field(
        default_factory=lambda: OrchestratorSegmentConfig(min_turns=10, max_turns=20)
    )
    deep_dive: OrchestratorSegmentConfig = Field(
        default_factory=lambda: OrchestratorSegmentConfig(min_turns=25, max_turns=45)
    )
    conclusion: OrchestratorSegmentConfig = Field(
        default_factory=lambda: OrchestratorSegmentConfig(min_turns=10, max_turns=20)
    )


class ScriptGeneratorConfig(BaseModel):
    """台本生成エンジン設定"""
    default_provider: str = "gemini"
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    structure: ScriptStructureConfig = Field(default_factory=ScriptStructureConfig)
    currency: CurrencyConfig = Field(default_factory=CurrencyConfig)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)


class SpeakersConfig(BaseModel):
    """話者ID設定"""
    main: int = 3  # ずんだもん
    sub: int = 2   # 四国めたん


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
    use_gpu: bool = True  # GPU加速（NVENC）を使用
    bgm_volume: float = 0.15
    bgm_fade_in_sec: float = 3.0
    bgm_fade_out_sec: float = 3.0
    # スペクトラム可視化設定
    enable_spectrum: bool = True
    spectrum_color: str = "0x00FF88"
    spectrum_mode: str = "cline"
    # 背景画像生成設定
    background_mode: str = "static"  # "static" or "dynamic"
    thumbnail_background_mode: str = "static"  # "static" or "dynamic"


class FluxConfig(BaseModel):
    """FLUX.1 (Forge API) 設定"""
    base_url: str = "http://127.0.0.1:7890"
    timeout: int = 120
    steps: int = 20
    width: int = 1344
    height: int = 768
    sampler_name: str = "Euler"
    scheduler: str = "Simple"
    cfg_scale: float = 1.0
    enable_pre_generation_cleanup: bool = True
    enable_resolution_fallback: bool = True
    fallback_resolutions: list[list[int]] = [[896, 504], [768, 432], [640, 360]]


class ComfyUIConfig(BaseModel):
    """ComfyUI API 設定"""
    base_url: str = "http://127.0.0.1:8188"
    workflow_path: str = "config/workflow_api.json"
    timeout: int = 600
    steps: int = 4
    width: int = 768
    height: int = 432
    cfg: float = 1.0
    sampler_name: str = "euler"
    scheduler: str = "normal"


class VideoConfig(BaseModel):
    """動画表示設定（オーバーレイ等）"""
    show_topic_overlay: bool = True


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


class DevConfig(BaseModel):
    """開発用設定（Mockモード等）"""
    mock_mode: bool = Field(default=False)
    mock_data_path: str = Field(default="tests/mock_data")
    mock_skip_metadata: bool = Field(default=False)
    mock_skip_thumbnail: bool = Field(default=False)


class PublishingConfig(BaseModel):
    """公開・配信設定（YouTube等）"""
    enable_upload: bool = Field(default=False)
    privacy_status: str = Field(default="unlisted")
    category_id: str = Field(default="27")  # Education
    playlist_id: str = Field(default="")
    default_tags: List[str] = Field(
        default_factory=lambda: ["#ずんだもん", "#VOICEVOX", "#AI", "#ラジオ"]
    )
    footer_text: str = Field(
        default=(
            "-----------------------------------\n"
            "■使用音声\n"
            "VOICEVOX:ずんだもん\n"
            "VOICEVOX:四国めたん\n"
            "-----------------------------------"
        )
    )


class YamlConfig(BaseModel):
    """config.yamlから読み込む設定"""
    researcher: ResearcherConfig = Field(default_factory=ResearcherConfig)
    script_generator: ScriptGeneratorConfig = Field(default_factory=ScriptGeneratorConfig)
    audio_synthesizer: AudioSynthesizerConfig = Field(default_factory=AudioSynthesizerConfig)
    video_renderer: VideoRendererConfig = Field(default_factory=VideoRendererConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    flux: FluxConfig = Field(default_factory=FluxConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    image_provider: str = "forge"  # "forge" or "comfyui"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    personalities: PersonalitiesConfig = Field(default_factory=PersonalitiesConfig)
    dev: DevConfig = Field(default_factory=DevConfig)  # 開発用設定
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)

    @model_validator(mode="after")
    def validate_image_provider(self):
        """Validate image_provider value"""
        valid_providers = {"forge", "comfyui"}
        if self.image_provider not in valid_providers:
            raise ValueError(
                f"Invalid image_provider: '{self.image_provider}'. "
                f"Must be one of: {', '.join(sorted(valid_providers))}"
            )
        return self


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
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
            yaml_config = YamlConfig.model_validate(yaml_data)
        except Exception as e:
            print(f"WARNING: YAML設定読み込み失敗: {e}")
            print(f"デフォルト設定を使用します")
            yaml_config = YamlConfig()
    else:
        print(f"WARNING: YAML設定ファイルが見つかりません: {yaml_path}")
        print(f"デフォルト設定を使用します")
        yaml_config = YamlConfig()
    
    return AppConfig(
        env=env_settings,
        yaml=yaml_config,
        project_root=project_root
    )
