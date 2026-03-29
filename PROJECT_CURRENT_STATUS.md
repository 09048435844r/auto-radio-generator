# プロジェクト現況レポート: Auto Radio Generator

**生成日時**: 2026-03-30 02:40:00
**バージョン**: v3.5.0+ (unreleased fixes)
**ブランチ**: main

---

## 1. Directory Structure

```
auto_radio_generator/
├── .env.example                 # Environment variables template
├── .gitignore                   # Git ignore rules
├── README.md                    # Project documentation
├── requirements.txt             # Python dependencies
├── config.yaml                  # Main configuration file
├── app.py                       # Gradio Web UI (main entry point)
├── main.py                      # CLI entry point
├── workflow.py                  # Core workflow orchestration
├── run.bat                      # Windows launcher (CLI)
├── run_webui.bat               # Windows launcher (Web UI)
│
├── core/                        # Core modules
│   ├── __init__.py
│   ├── prompt_manager.py        # Prompt template manager
│   ├── settings_manager.py      # User settings persistence
│   ├── models/                  # Data models
│   │   ├── __init__.py
│   │   ├── config.py            # Configuration models
│   │   ├── script.py            # Script data models
│   │   ├── research.py          # Research result models
│   │   └── usage.py             # API usage tracking models
│   └── interfaces/              # Abstract interfaces
│       ├── __init__.py
│       ├── script_generator.py  # IScriptGenerator interface
│       ├── researcher.py        # IResearcher interface
│       └── audio_synthesizer.py # IAudioSynthesizer interface
│
├── services/                    # Service layer
│   ├── __init__.py
│   ├── cost_calculator.py       # API cost calculation
│   ├── script_generation/       # Script generation services
│   │   ├── __init__.py
│   │   ├── gemini_client.py     # Gemini API client (台本生成)
│   │   └── time_expressions.py  # Time expression utilities
│   ├── research/                # Research services
│   │   ├── __init__.py
│   │   └── perplexity_client.py # Perplexity API client (リサーチ)
│   ├── audio_synthesis/         # Audio synthesis services
│   │   ├── __init__.py
│   │   └── voicevox_client.py   # VOICEVOX API client
│   ├── video_rendering/         # Video rendering services
│   │   ├── __init__.py
│   │   └── ffmpeg_renderer.py   # FFmpeg wrapper
│   └── media_processing/        # Media processing services
│       ├── __init__.py
│       └── thumbnail_generator.py # Thumbnail image generator
│
├── config/                      # Configuration files
│   └── prompts.yaml             # Prompt templates (台本生成・パッケージング)
│
├── assets/                      # Static assets
│   ├── backgrounds/             # Background images (1920x1080)
│   ├── bgm/                     # Background music files
│   └── fonts/                   # Japanese fonts for thumbnails
│
└── output/                      # Generated content (gitignored)
    └── YYYYMMDD_HHMMSS/         # Timestamped output folders
        ├── research.json        # Research results
        ├── script.json          # Generated script
        ├── metadata.txt         # YouTube metadata
        ├── video_metadata.json  # AI-generated metadata
        ├── thumbnail.png        # Thumbnail image
        ├── processing_log.txt   # Execution log
        ├── audio/               # Audio files
        │   ├── combined_audio.wav
        │   └── subtitles.ass
        └── videos/              # Final video output
            └── radio_*.mp4
```

---

## 2. Environment & Dependencies

### 2.1 Python Dependencies (`requirements.txt`)

```txt
# Configuration & Validation
pydantic>=2.0.0          # データモデル定義
pydantic-settings>=2.0.0 # 設定管理
python-dotenv>=1.0.0     # 環境変数読み込み
PyYAML>=6.0.0            # YAML設定ファイル

# AI APIs
google-genai>=1.0.0      # Gemini API (台本生成)
openai>=1.0.0            # Perplexity API (リサーチ、OpenAI互換)

# Audio Processing
pydub>=0.25.1            # 音声ファイル操作
numpy>=1.24.0            # 音声データ処理

# Image Processing
Pillow>=10.0.0           # サムネイル生成
budoux>=0.6.0            # 日本語の自然な改行

# HTTP Client
httpx>=0.27.0            # VOICEVOX API通信（非同期対応）

# CLI & Utilities
rich>=13.0.0             # コンソール出力装飾

# Web UI
gradio>=4.0.0            # ブラウザベースUI（タブ式インターフェース）

# External Dependencies (要手動インストール):
# - VOICEVOX Engine: https://voicevox.hiroshiba.jp/
# - FFmpeg: https://ffmpeg.org/
```

### 2.2 Environment Variables (`.env.example`)

```env
# Perplexity API Key (https://www.perplexity.ai/)
PERPLEXITY_API_KEY=pplx-********************************

# Google Gemini API Key (https://aistudio.google.com/)
GEMINI_API_KEY=AIzaSy*************************************

# VOICEVOX Engine URL (ローカルで起動している場合)
VOICEVOX_BASE_URL=http://localhost:50021
```

### 2.3 Configuration Overview (`config.yaml`)

| セクション | 内容 |
|-----------|------|
| `researcher` | Perplexity API設定（5つのリサーチモード: debate/voices/trivia/weekly_digest/lecture） |
| `script_generator` | Gemini API設定（model: gemini-3-pro-preview, fallback: gemini-2.5-pro） |
| `audio_synthesizer` | VOICEVOX設定（speaker IDs, speed, pitch, pause） |
| `video_renderer` | FFmpeg設定（1920x1080, NVENC GPU対応, loudnorm, spectrum可視化） |
| `paths` | アセット・出力ディレクトリ設定 |
| `personalities` | キャラクター定義（ずんだもん / めたん） |
| `dev` | 開発用設定（mock_mode, mock_data_path） |

---

## 3. Implementation Skeleton (Key Files)

### 3.1 Entry Points

#### `app.py` — Gradio Web UI (1885行)

```python
"""自動ラジオ動画生成システム - Gradio Web UI v3.2.0"""
import gradio as gr
from workflow import UIOverrides, run_workflow_sync, WorkflowResult, scan_assets, create_script_generator, load_config
from core.models import Script
from core.interfaces import ResearchResult
from core.settings_manager import SettingsManager

_log_messages: list[str] = []
_settings_manager = SettingsManager()

def clear_logs() -> None: ...
def append_log(msg: str) -> None: ...
def get_logs() -> str: ...

def generate_video(
    theme: str, research_mode: str, background_image: str, bgm_file: str,
    bgm_volume: float, fade_time: float, speed_scale: float,
    enable_spectrum: bool, use_mock: bool = False, avoid_topics: str = "",
    progress=gr.Progress()
) -> tuple[str | None, str, str, str, str]:
    """自動生成タブのメイン処理 → run_workflow_sync を呼び出し"""
    ...

def generate_script_only(theme: str, research_mode: str, progress=gr.Progress()) -> tuple[str, str]:
    """台本のみ生成（AIプロデューサー → リサーチ → 台本）"""
    ...

def synthesize_audio_from_script(script_json: str, progress=gr.Progress()) -> tuple[...]:
    """台本JSONから音声合成"""
    ...

def render_video_from_assets(audio_path, subtitle_path, background_path, ..., progress=gr.Progress()) -> tuple[...]:
    """アセットから動画レンダリング"""
    ...

def generate_script_from_research(research_text: str, theme: str, progress=gr.Progress()) -> tuple[str, str]:
    """リサーチテキストから台本生成"""
    ...

# --- Step Mode (こだわりステップモード) ---
def execute_step0_planning(theme, research_mode, progress) -> tuple[str, str, str, str]: ...
def execute_step1_scripting(theme, research_mode, query1, query2, query3, progress) -> tuple[...]: ...
def execute_step2_production(title, description, script_json, ..., progress) -> tuple[str | None, str]: ...

def create_ui() -> gr.Blocks:
    """Gradio UIを作成"""
    # Tab 1: 🚀 動画生成（自動）
    # Tab 2: 🎛️ こだわりステップモード（Step 0→1→2）
    # Tab 3: 📝 マニュアル制作（台本→音声→動画）
    # Tab 4: 📖 使い方
    ...

def main():
    app = create_ui()
    app.launch(server_name="0.0.0.0", server_port=7860)
```

#### `workflow.py` — Core Workflow Orchestration (1351行)

```python
"""自動ラジオ動画生成システム - 共通ワークフロー関数"""

@dataclass
class UIOverrides:
    research_mode: Optional[ResearchMode] = None
    enable_research: bool = True
    bgm_volume: Optional[float] = None
    fade_in_sec: Optional[float] = None
    fade_out_sec: Optional[float] = None
    enable_spectrum: Optional[bool] = None
    speed_scale: Optional[float] = None
    background_image: Optional[str] = None
    bgm_file: Optional[str] = None

@dataclass
class WorkflowResult:
    success: bool
    video_path: Optional[Path] = None
    script: Optional[Script] = None
    audio_path: Optional[Path] = None
    subtitle_path: Optional[Path] = None
    duration_sec: float = 0.0
    file_size_mb: float = 0.0
    error_message: Optional[str] = None
    usage: Optional[TotalUsage] = None
    cost: Optional[CostBreakdown] = None
    cost_report: str = ""
    metadata_content: str = ""
    formatted_title: str = ""
    formatted_description: str = ""

@dataclass
class PlanningPhaseResult:
    queries: list[str]; angle: str; gemini_usage: Optional[GeminiUsage] = None; ...

@dataclass
class ScriptingPhaseResult:
    script: Script; research_content: Optional[str] = None; ...

@dataclass
class ProductionPhaseResult:
    video_path: Path; audio_path: Path; subtitle_path: Path; chapters: list[ChapterMarker]; ...

@dataclass
class ProgressCallback:
    log_callback: Optional[Callable] = None
    progress_callback: Optional[Callable] = None
    def log(self, msg: str): ...
    def progress(self, ratio: float, description: str): ...

class LogFileWriter:
    def __init__(self, output_dir: Path): ...
    def write(self, msg: str): ...
    def finalize(self): ...

async def execute_planning_phase(theme, mode, config, instruction=None, callbacks=None) -> PlanningPhaseResult:
    """Phase 1: AIプロデューサーが検索計画を作成"""
    ...

async def execute_scripting_phase(
    theme, mode, queries, config, output_dir,
    enable_research=True, excluded_topics=None, avoid_topics=None, callbacks=None
) -> ScriptingPhaseResult:
    """Phase 2: リサーチ → 台本生成（avoid_topics=Negative Prompt対応）"""
    ...

async def execute_production_phase(script, config, output_dir, project_root, speed_scale=None, callbacks=None) -> ProductionPhaseResult:
    """Phase 3: 音声合成 → 動画生成 → サムネイル"""
    ...

def run_workflow_sync(
    theme, overrides=None, log_callback=None, progress_callback=None,
    use_mock=False, avoid_topics=None
) -> WorkflowResult:
    """同期ワークフロー実行（app.pyから呼び出し）"""
    # Phase 1: 企画（検索計画作成）
    # Phase 2: 台本作成（リサーチ + 台本生成）
    # Phase 3: 制作（音声合成 + 動画生成）
    # Phase 4: 後処理（YouTubeメタデータ + サムネイル + コスト計算）
    ...

def _generate_youtube_metadata(script, chapters, output_path, theme="") -> dict:
    """YouTube投稿用メタデータ生成（Gemini packaging prompt使用）"""
    # 成功時: {"title": ..., "thumbnail_title": ..., "description": ...}
    # 失敗時: フォールバックでscript.title/descriptionを使用
    ...
```

#### `main.py` — CLI Entry Point (162行)

```python
"""自動ラジオ動画生成システム - メインエントリーポイント"""
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

def create_script_generator(config) -> IScriptGenerator: ...

async def main():
    # 1. 設定読み込み
    # 2. VOICEVOX/FFmpeg確認
    # 3. テーマ入力
    # 4. 台本生成 → プレビュー → 続行確認
    # 5. 音声合成 → 動画生成
    ...
```

---

### 3.2 Data Models

#### `core/models/script.py`

```python
SpeakerID = Literal["A", "B"]

class DialogueLine(BaseModel):
    speaker: SpeakerID          # "A" or "B"
    text: str                   # セリフ本文（空文字不可）
    emotion: Optional[str]      # 感情指定
    section: Optional[str]      # セクションマーカー（チャプター用）

    @model_validator(mode='before')
    def upgrade_legacy_data(cls, data): ...  # speaker_id → speaker 自動変換

class Script(BaseModel):
    title: str                          # ラジオのタイトル
    theme: str = ""                     # テーマ
    sections: List[DialogueLine]        # 会話リスト（最低10ターン）
    thumbnail_title: Optional[str]      # サムネイル用タイトル
    description: Optional[str]          # 概要欄テキスト

    @model_validator(mode='before')
    def convert_dialogue_to_sections(cls, data): ...  # dialogue → sections 自動変換

    @property
    def dialogue(self) -> List[DialogueLine]: return self.sections  # 後方互換
```

#### `core/models/config.py`

```python
class EnvSettings(BaseSettings):
    """環境変数（.env）"""
    perplexity_api_key: str = Field(default="", alias="PERPLEXITY_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    voicevox_base_url: str = Field(default="http://localhost:50021", alias="VOICEVOX_BASE_URL")

class YamlConfig(BaseModel):
    """config.yaml全体"""
    researcher: ResearcherConfig
    script_generator: ScriptGeneratorConfig
    audio_synthesizer: AudioSynthesizerConfig
    video_renderer: VideoRendererConfig
    paths: PathsConfig
    personalities: PersonalitiesConfig
    dev: DevConfig  # mock_mode, mock_data_path

class AppConfig(BaseModel):
    """統合設定"""
    env: EnvSettings
    yaml: YamlConfig
    project_root: Path

def load_config(project_root=None, config_file="config.yaml") -> AppConfig: ...
```

#### `core/models/research.py`

```python
class ResearchSource(BaseModel):
    title: str; url: str; snippet: Optional[str]

class ResearchResult(BaseModel):
    query: str; raw_content: str; sources: List[ResearchSource]
    timestamp: Optional[str]; provider: str = "perplexity"
    mode: Optional[str]; content: Optional[str]  # 後方互換

class ResearchPlan(BaseModel):
    queries: list[str]  # 検索クエリリスト（1-5個）
    angle: str          # 台本の切り口
```

#### `core/models/usage.py`

```python
@dataclass
class PerplexityUsage:
    request_count: int = 0

@dataclass
class GeminiUsage:
    input_tokens: int = 0; output_tokens: int = 0; request_count: int = 0; model_name: str = ""

@dataclass
class VoicevoxUsage:
    phrase_count: int = 0; total_duration_sec: float = 0.0

@dataclass
class TotalUsage:
    perplexity: PerplexityUsage; gemini: GeminiUsage; voicevox: VoicevoxUsage
    total_duration_sec: float = 0.0; research_duration_sec: float = 0.0; ...

@dataclass
class CostBreakdown:
    perplexity_usd: float = 0.0; gemini_input_usd: float = 0.0; ...
    total_usd: float = 0.0; total_jpy: float = 0.0; is_free_tier: bool = False
```

---

### 3.3 Interfaces (`core/interfaces/`)

```python
# researcher.py
ResearchMode = Literal["debate", "voices", "trivia", "weekly_digest", "lecture"]

@dataclass
class ResearchResult:
    topic: str; mode: ResearchMode; content: str; sources: list[str] | None; usage: PerplexityUsage | None

class IResearcher(ABC):
    async def research(self, topic: str, mode: ResearchMode) -> ResearchResult: ...
    async def check_api_status(self) -> bool: ...

# script_generator.py
class IScriptGenerator(ABC):
    async def generate(self, theme: str, research_data: Optional[ResearchResult] = None) -> Script: ...

# audio_synthesizer.py
@dataclass
class ChapterMarker:
    start_time_sec: float; title: str; section_id: str

@dataclass
class SynthesisResult:
    audio_path: Path; subtitle_path: Path; total_duration_sec: float; chapters: list[ChapterMarker]

class IAudioSynthesizer(ABC):
    async def synthesize(self, script: Script, output_dir: Path) -> SynthesisResult: ...
    async def check_engine_status(self) -> bool: ...

# video_renderer.py
@dataclass
class RenderResult:
    video_path: Path; duration_sec: float; file_size_mb: float

class IVideoRenderer(ABC):
    async def render(self, synthesis_result, background_image, bgm_file, output_path, subtitle_path=None) -> RenderResult: ...
    def check_ffmpeg_available(self) -> bool: ...
```

---

### 3.4 Service Layer

#### `services/script_generation/gemini_client.py` (446行)

```python
class GeminiClient(IScriptGenerator):
    def __init__(self, config: AppConfig):
        self.client = genai.Client(api_key=config.env.gemini_api_key)
        self.model_name = config.yaml.script_generator.gemini.model          # gemini-3-pro-preview
        self.fallback_model = config.yaml.script_generator.gemini.fallback_model  # gemini-2.5-pro
        self.prompt_manager = PromptManager()
        self.last_usage: GeminiUsage | None = None

    async def create_research_plan(self, theme, mode, instruction=None) -> ResearchPlan:
        """AIプロデューサー: テーマから検索計画を作成（フォールバックモデル対応）"""
        ...

    def generate(self, theme, research_data=None, avoid_topics=None) -> Script:
        """台本生成（Mock対応、Negative Prompt対応、フォールバックモデル対応）"""
        # response_schema=Script でPydantic構造化出力を強制
        ...

    def _call_api(self, system_prompt, user_prompt, use_schema=False) -> tuple[str, GeminiUsage]:
        """Gemini API呼び出し（JSON Mode + response_schema）"""
        ...

    def _build_user_prompt(self, theme, research_data, avoid_topics=None) -> str:
        """ユーザープロンプト構築（avoid_topics → [NEGATIVE CONSTRAINTS]セクション注入）"""
        ...

    def _parse_response(self, response_text) -> Script:
        """JSONパース → Pydanticバリデーション"""
        ...

    def generate_packaging_prompt(self, theme, script_summary) -> str:
        """packagingプロンプトでYouTubeメタデータ生成"""
        ...
```

#### `services/research/perplexity_client.py` (222行)

```python
class PerplexityResearcher(IResearcher):
    def __init__(self, config: AppConfig):
        self.client = OpenAI(api_key=config.env.perplexity_api_key, base_url="https://api.perplexity.ai")
        self.prompt_manager = PromptManager()

    async def research(self, topic, mode) -> ResearchResult:
        """単一クエリリサーチ（Mock対応）"""
        ...

    async def research_multi(self, queries: list[str], mode) -> ResearchResult:
        """複数クエリ並列リサーチ（asyncio.gather）+ 引用情報抽出"""
        ...

    async def check_api_status(self) -> bool: ...
```

#### `services/audio_synthesis/voicevox_client.py` (343行)

```python
class VoicevoxClient(IAudioSynthesizer):
    def __init__(self, config: AppConfig):
        self.base_url = config.env.voicevox_base_url
        self.speakers = config.yaml.audio_synthesizer.speakers  # main=3(ずんだもん), sub=2(めたん)

    async def synthesize(self, script, output_dir, speed_scale_override=None) -> SynthesisResult:
        """台本→音声合成（Mock対応、チャプターマーカー生成、ASS字幕生成）"""
        # 冒頭2秒 + 音声合成 + 末尾5秒の無音追加
        ...

    async def _synthesize_phrase(self, client, text, speaker_id, speed_scale) -> bytes: ...
    def _combine_audio(self, phrase_data, pause_ms) -> AudioSegment: ...
    def _generate_ass(self, phrase_data, output_path) -> None:
        """ASS字幕生成（話者ごとに色分け、BudouXで自然な改行）"""
        ...
    def _get_chapter_title(self, section_id, text) -> str: ...
```

#### `services/video_rendering/ffmpeg_renderer.py` (319行)

```python
class FfmpegRenderer(IVideoRenderer):
    def __init__(self, config: AppConfig):
        self.video_config = config.yaml.video_renderer
        self.ffmpeg_path = self._find_ffmpeg()

    async def render(self, synthesis_result, background_image, bgm_file, output_path, subtitle_path=None) -> RenderResult:
        """動画生成（デバッグログ付き）"""
        ...

    def _build_ffmpeg_command(self, background_image, audio_file, bgm_file, subtitle_file, output_path, ...) -> list[str]:
        """FFmpegコマンド構築"""
        # BGMフィルタ: volume → afade in/out
        # 音声ミックス: amix → loudnorm (I=-14, TP=-1, LRA=11) ← YouTube推奨
        # 字幕: Windows絶対パスエスケープ（\→/, :→\:）
        # 日付表示: drawtext（右上透かし）
        # スペクトラム: showwaves → overlay
        # GPU切替: use_gpu → h264_nvenc (p4/vbr/cq23) or libx264 (medium/crf23)
        ...

    def check_ffmpeg_available(self) -> bool: ...
```

#### `services/media_processing/thumbnail_generator.py` (552行)

```python
class ThumbnailGenerator:
    THUMBNAIL_WIDTH = 1280; THUMBNAIL_HEIGHT = 720

    def generate(self, title, background_path, output_path, thumbnail_title="", ...) -> Path:
        """サムネイル生成（センターセーフ方式: 1:1トリミング対応）"""
        ...

    def _draw_title_text(self, img, title) -> Image.Image:
        """BudouXで自然改行、フォントサイズ自動調整（180→40px）、黒フチ白文字"""
        ...

    def _draw_date_badge(self, img) -> Image.Image:
        """セーフエリア内右上に赤バッジ "YYYY.MM.DD制作" """
        ...
```

#### `services/cost_calculator.py` (171行)

```python
class CostCalculator:
    def calculate(self, usage: TotalUsage) -> CostBreakdown:
        """Perplexity: $0.005/req, Gemini: $1.25/$5.00 per 1M tokens, VOICEVOX: $0"""
        ...

    def format_cost_report(self, usage, cost) -> str:
        """Markdown形式のコストレポート生成"""
        ...
```

---

### 3.5 Core Utilities

#### `core/prompt_manager.py` (120行)

```python
class PromptManager:
    """config/prompts.yaml からプロンプトを読み込むシングルトン"""
    def get_research_prompt(self, mode: str) -> str: ...
    def get_script_prompt(self, prompt_type: str, **kwargs) -> str: ...
    def get_prompt(self, section: str, key: str = "default") -> str: ...
    def get_component(self, name: str) -> str: ...
    def reload(self) -> None: ...
```

#### `core/settings_manager.py` (113行)

```python
@dataclass
class UserSettings:
    research_mode: str = "トリビア (雑学)"
    background_image: Optional[str] = None
    bgm_file: Optional[str] = None
    bgm_volume: float = 0.15; fade_time: float = 3.0
    speed_scale: float = 1.1; enable_spectrum: bool = True

class SettingsManager:
    def load(self) -> UserSettings: ...
    def save(self, settings: UserSettings): ...
    def update_from_ui(self, research_mode, background_image, ...): ...
```

---

## 4. Current Status & Issues

### 4.1 Git History (直近10コミット)

```
42aede6 Fix: Metadata (title/description) missing bug
3e4d6bd Refactor: Release v3.2.0 (Added Negative Prompt, Loudness Norm, Progress UI)
96cfcec Backup: Before maintenance v3.2.0
79dd263 Feat: Add negative prompt (avoid_topics) to UI and script generation (Retry)
56a69bc Feat: Add audio loudness normalization (-14 LUFS) for YouTube
09429d9 Refactor: Cleanup code and update docs for v3.1.2 (GPU/Mock/UI)
4d7f2ca Feat: Add progress visualization with Gradio progress bar
ec163cf Fix: Replace all speaker_id references with speaker attribute
03b764c Fix: Replace speaker_id with speaker attribute in voicevox_client
186ad8b Fix: Add missing 'section' field to DialogueLine model
```

### 4.2 v3.2.0 新機能（直近で追加）

| 機能 | 対象ファイル | 状態 |
|------|------------|------|
| **Negative Prompt** (避けてほしい話題) | `app.py`, `workflow.py`, `gemini_client.py` | ✅ 実装済み |
| **Loudness Normalization** (-14 LUFS) | `ffmpeg_renderer.py` | ✅ 実装済み |
| **Visual Progress Bar** | `app.py`, `workflow.py` | ✅ 実装済み |
| **Mock Mode** (API課金なしテスト) | 全サービスファイル | ✅ 実装済み |
| **NVENC GPU Acceleration** | `ffmpeg_renderer.py`, `config.yaml` | ✅ 実装済み |
| **Metadata Bug Fix** (タイトル/概要欄が空になるバグ) | `workflow.py` | ✅ 修正済み |

### 4.3 Known Issues & TODOs

**TODOコメント**: プロジェクト内に `TODO` / `FIXME` コメントは **0件**。

**最近修正された課題（v3.5.0+）:**
1. ✅ **動画途切れ問題** — 末尾5秒のpost-rollがセグメントタイミングに含まれず、動画が音声より短くなる問題を修正
2. ✅ **FLUX.1タイムアウト** — 低VRAM環境での処理時間超過を、設定最適化（timeout延長、ステップ削減、解像度低下）で解決
3. ✅ **Dynamic mode フォールバック失敗** — FLUX.1失敗時に静的画像が見つからないエラーを修正
4. ✅ **Visual Palette型エラー** — 型アノテーションバグ（`Any`未インポート、`any`→`Any`）を修正
5. ✅ **アーキテクチャの改善** — Phase 2.5を廃止し、データの不変性を確保

**既知の課題:**
1. **YouTube自動アップロード未実装** — 現在は手動でアップロード
2. **ログの長期保存未対応** — 各実行ごとのテキストログのみ（DB/JSONL蓄積なし）
3. **コスト追跡の永続化なし** — 月次推移の可視化ができない
4. **テスト不足** — ユニットテスト・統合テストが未整備
5. **`_generate_youtube_metadata`** — Gemini packaging呼び出しが失敗するとフォールバック動作（script.title使用）

### 4.4 Dependencies Status

| 依存 | 状態 | 備考 |
|------|------|------|
| VOICEVOX Engine | ✅ | `http://localhost:50021` で起動必須 |
| FFmpeg | ✅ | PATH上に必要、NVENC使用時はNVIDIA GPU必須 |
| Gemini API | ✅ | `GEMINI_API_KEY` 必須 |
| Perplexity API | ✅ | `PERPLEXITY_API_KEY` 必須 |
| Python | ✅ | 3.10+ 必須 |

---

## 5. Architecture Overview

### 5.1 Workflow Pipeline

```
User Input (Theme + avoid_topics)
    ↓
[Phase 1] 企画 — AIプロデューサーが検索計画を作成 (Gemini)
    ↓
[Phase 2-1] リサーチ — 複数クエリ並列実行 (Perplexity)
    ↓
[Phase 2-2] 台本生成 — JSON Mode + response_schema (Gemini)
    ↓
[Phase 3-1] 音声合成 — 話者別合成 + ASS字幕 + チャプター (VOICEVOX)
    ↓
[Phase 3-2] 動画生成 — BGM + loudnorm + spectrum + NVENC (FFmpeg)
    ↓
[Phase 3-3] サムネイル生成 — BudouX改行 + センターセーフ (Pillow)
    ↓
[Phase 4] 後処理 — YouTubeメタデータ + コスト計算 (Gemini packaging)
    ↓
Final Output (MP4 + metadata.txt + thumbnail.png + video_metadata.json)
```

### 5.2 Key Design Patterns

1. **Interface First** — `core/interfaces/` に抽象クラスを定義してから実装
2. **Config Driven** — 全設定値は `config.yaml` + `.env` で管理
3. **Pydantic Models** — 型安全なデータバリデーション + 後方互換性バリデータ
4. **Async/Await** — 非同期API呼び出し + asyncio.gather並列実行
5. **Graceful Degradation** — GPU→CPU, API→Mock, メインモデル→フォールバックモデル

---

## 6. Output Structure

```
output/YYYYMMDD_HHMMSS/
├── research.json           # リサーチ生データ
├── research_report.md      # リサーチレポート（Markdown）
├── full_research_report.md # Perplexity全文レポート
├── script.json             # 生成された台本（Pydantic JSON）
├── video_metadata.json     # AI生成メタデータ（title, thumbnail_title, description）
├── metadata.txt            # YouTube投稿用メタデータ（整形済み）
├── thumbnail.png           # サムネイル画像（1280x720）
├── processing_log.txt      # 実行ログ
├── audio/
│   ├── combined_audio.wav  # 最終音声トラック
│   └── subtitles.ass       # ASS字幕ファイル（話者色分け）
└── videos/
    └── radio_*.mp4         # 最終動画出力
```

---

## 7. 現状仕様メモ（YouTube概要欄・チャプター生成）

### 7.1 Description の構築元

- YouTubeアップロード時の `description` は `workflow.py` の `formatted_description` を使用。
- 構成は以下の順序:
  1. チャプター行（`MM:SS タイトル`、存在する場合のみ）
  2. `script.description`
  3. 固定ハッシュタグ（`#ずんだもん #VOICEVOX #AI #ラジオ`）
- `_generate_youtube_metadata()` でも AI 生成の説明文を作るが、アップロード時の payload は `formatted_description` 側が優先される。

### 7.2 チャプター時刻の算出

- `start_time_sec` は VOICEVOX 合成処理中に、各フレーズの実際の音声長（ms）を累積して算出。
- そのため時刻は予測値ではなく、実測ベースの累積時間。
- ただし冒頭2秒の無音を入れる設計のため、チャプター時刻には `+2.0s` オフセットが加算される。

### 7.3 モード差分

- **Topic Mode（テーマ入力）**
  - チャプタータイトルは `line.section` と発話テキストから `_get_chapter_title()` で生成。
  - タイトル文言の元データは LLM 出力台本に依存するため、英語混在を抑止する専用正規化は現状なし。
- **URL Mode（記事URL入力）**
  - URL専用の入力フロー/分岐は現状未実装。
  - 記事要約やURLリンクを概要欄へ特化挿入する専用ロジックも未実装。
- **Mock Mode**
  - planning/research はダミークエリで進行。
  - 音声合成のMock結果では `chapters=[]` になるため、概要欄は実質 `script.description + 固定ハッシュタグ` 構成になりやすい。

### 7.4 UI表示テキストとの一致性

- `YouTubeClient.upload_video(..., description=...)` には `formatted_description` をそのまま渡している。
- `WorkflowResult.formatted_description` も同じ文字列を保持し、UI「一括コピー用」表示に使うため、両者は同一。

---

## 8. Contact & Support

**Project Repository:** https://github.com/09048435844r/auto-radio-generator
**Tech Lead:** AI Assistant (Cascade)
**Current Branch:** `main`
**Last Updated:** 2026-02-15

---

**End of Report**
