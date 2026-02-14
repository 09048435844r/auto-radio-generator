# 🎙️ Auto Radio Generator - Project Current Status Report

**Generated:** 2026-02-07  
**Version:** v3.2.0 (GPU / Mock / UI)  
**Branch:** master

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
pydantic>=2.0.0          # Data model definitions
pydantic-settings>=2.0.0 # Settings management
python-dotenv>=1.0.0     # Environment variable loading
PyYAML>=6.0.0            # YAML configuration files

# AI APIs
google-genai>=1.0.0      # Gemini API (script generation)
openai>=1.0.0            # Perplexity API (research, OpenAI-compatible)

# Audio Processing
pydub>=0.25.1            # Audio file manipulation
numpy>=1.24.0            # Audio data processing

# Image Processing
Pillow>=10.0.0           # Thumbnail generation
budoux>=0.6.0            # Natural Japanese line breaks

# HTTP Client
httpx>=0.27.0            # VOICEVOX API communication (async support)

# CLI & Utilities
rich>=13.0.0             # Console output decoration

# Web UI
gradio>=4.0.0            # Browser-based UI (tab interface)

# External Dependencies (manual installation required):
# - VOICEVOX Engine: https://voicevox.hiroshiba.jp/
# - FFmpeg: https://ffmpeg.org/
```

### 2.2 Environment Variables (`.env.example`)

```env
# Perplexity API Key (https://www.perplexity.ai/)
PERPLEXITY_API_KEY=pplx-********************************

# Google Gemini API Key (https://aistudio.google.com/)
GEMINI_API_KEY=AIzaSy*************************************

# VOICEVOX Engine URL (when running locally)
VOICEVOX_BASE_URL=http://localhost:50021
```

### 2.3 Configuration Overview (`config.yaml`)

**Key Settings:**
- **Researcher**: Perplexity API configuration (5 research modes)
- **Script Generator**: Gemini API configuration (台本生成)
- **Audio Synthesizer**: VOICEVOX settings (speaker IDs, speed, pitch)
- **Video Renderer**: FFmpeg settings (resolution, codec, bitrate)
- **Personalities**: Character definitions (main/sub speakers)

---

## 3. Implementation Skeleton (Key Files)

### 3.1 Entry Points

#### `app.py` - Gradio Web UI (Main Entry Point)

```python
"""自動ラジオ動画生成システム - Gradio Web UI
v3.1.1 機能:
- タブ式UI: 自動生成とマニュアル制作を分離
- マニュアル制作ワークフロー: Step A(台本) → Step B(音声) → Step C(動画)
- 設定の永続化: ユーザー設定を自動保存・復元
- 処理ログ出力: 各実行の詳細ログをファイルに保存
"""

# Global state management
_log_buffer: list[str] = []
_settings_manager = SettingsManager(PROJECT_ROOT / "user_settings.json")

def append_log(message: str) -> None:
    """ログバッファに追加"""
    # ...

def clear_logs() -> None:
    """ログバッファをクリア"""
    # ...

def generate_video_auto(
    theme: str,
    research_mode: str,
    enable_research: bool,
    # ... other parameters
) -> tuple[Path | None, str, str, str, str]:
    """自動生成タブのメイン処理"""
    # 1. リサーチ実行
    # 2. 台本生成
    # 3. 音声合成
    # 4. 動画レンダリング
    # 5. サムネイル生成
    # 6. メタデータ生成
    # ...

def generate_script_step_a(
    research_result: str,
    theme: str,
    progress=gr.Progress()
) -> tuple[str, str]:
    """Step A: 台本生成"""
    # ...

def synthesize_audio_step_b(
    script_json: str,
    # ... audio parameters
    progress=gr.Progress()
) -> tuple[str, str, str]:
    """Step B: 音声合成"""
    # ...

def render_video_step_c(
    audio_path: str,
    subtitle_path: str,
    # ... video parameters
    progress=gr.Progress()
) -> tuple[str, str]:
    """Step C: 動画レンダリング"""
    # ...

def create_ui() -> gr.Blocks:
    """Gradio UIを作成"""
    with gr.Blocks(title="自動ラジオ動画生成システム v3.1.1 (JSON Mode)") as app:
        # Tab 1: 自動生成 (Classic)
        # Tab 2: マニュアル制作 (Step-by-Step)
        # Tab 3: 使い方
        # ...
    return app

if __name__ == "__main__":
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
```

#### `workflow.py` - Core Workflow Orchestration

```python
"""ワークフロー実行エンジン"""

@dataclass
class WorkflowResult:
    """ワークフロー実行結果"""
    success: bool
    video_path: Optional[Path]
    script: Script
    audio_path: Optional[Path]
    subtitle_path: Optional[Path]
    duration_sec: float
    file_size_mb: float
    usage: TotalUsage
    cost: float
    cost_report: str
    metadata_content: str
    formatted_title: str
    formatted_description: str

def workflow(
    theme: str,
    config: Config,
    # ... parameters
) -> WorkflowResult:
    """メインワークフロー実行"""
    # 1. リサーチフェーズ
    # 2. 台本生成フェーズ
    # 3. 音声合成フェーズ
    # 4. 動画レンダリングフェーズ
    # 5. サムネイル生成フェーズ
    # 6. メタデータ生成フェーズ (packaging)
    # ...

def _generate_youtube_metadata(
    script: Script,
    chapters: list[ChapterMarker],
    output_path: Path,
    theme: str = ""
) -> dict:
    """YouTube投稿用のメタデータファイルを生成（packagingプロンプト使用）"""
    # Gemini APIでメタデータ生成
    # - title: AI生成タイトル
    # - thumbnail_title: サムネイル用キャッチフレーズ
    # - description: AI生成概要文
    # チャプター情報を概要欄の先頭に配置
    # ...
```

---

### 3.2 Data Models

#### `core/models/script.py`

```python
"""台本データモデル"""
from pydantic import BaseModel, Field
from typing import Literal, Optional

class DialogueLine(BaseModel):
    """対話の1行を表すモデル"""
    speaker_id: Literal["main", "sub"]
    text: str
    section: Optional[str] = None  # セクションマーカー

class Script(BaseModel):
    """台本全体を表すモデル"""
    title: str
    thumbnail_title: str = ""
    description: str
    dialogue: list[DialogueLine] = []
    
    def to_prompt_format(self) -> str:
        """プロンプト表示用のフォーマット"""
        # ...
```

#### `core/models/research.py`

```python
"""リサーチ結果データモデル"""
from pydantic import BaseModel

class ResearchResult(BaseModel):
    """リサーチ結果を表すモデル"""
    mode: str          # リサーチモード
    content: str       # リサーチ内容
    usage: dict        # API使用量
```

#### `core/models/usage.py`

```python
"""API使用量トラッキングモデル"""
from pydantic import BaseModel

class GeminiUsage(BaseModel):
    """Gemini API使用量"""
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    model_name: str = ""

class PerplexityUsage(BaseModel):
    """Perplexity API使用量"""
    # ...

class VoicevoxUsage(BaseModel):
    """VOICEVOX使用量"""
    # ...

class TotalUsage(BaseModel):
    """全体の使用量"""
    gemini: GeminiUsage
    perplexity: PerplexityUsage
    voicevox: VoicevoxUsage
    total_duration_sec: float = 0.0
```

---

### 3.3 Service Layer

#### `services/script_generation/gemini_client.py`

```python
"""Gemini API クライアント（台本生成）"""

class GeminiClient(IScriptGenerator):
    """Gemini APIを使用した台本生成クライアント"""
    
    def __init__(self, config: Config):
        self.config = config
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model_name = config.yaml.script_generator.model
        self.max_tokens = config.yaml.script_generator.max_tokens
    
    async def generate(
        self,
        theme: str,
        research_data: Optional[ResearchResult] = None
    ) -> Script:
        """台本を生成"""
        # 1. システムプロンプト取得
        # 2. ユーザープロンプト構築
        # 3. Gemini API呼び出し (JSON Mode有効)
        # 4. レスポンス解析
        # ...
    
    def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, GeminiUsage]:
        """Gemini APIを呼び出す"""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[...],
            config=types.GenerateContentConfig(
                max_output_tokens=self.max_tokens,
                temperature=0.85,
                response_mime_type="application/json",  # ★ JSON Mode有効化
            )
        )
        return response.text, usage
    
    def _parse_response(self, response_text: str) -> Script:
        """APIレスポンスからScriptオブジェクトを生成
        
        JSONモード有効化により、response_textは常に正しいJSON形式で返される
        """
        data = json.loads(response_text.strip())  # ★ シンプルな直接解析
        # Scriptオブジェクトに変換
        # ...
    
    def generate_packaging_prompt(self, theme: str, script_summary: str) -> str:
        """パッケージング用プロンプトでメタデータ生成"""
        # タイトル・サムネイル文字・概要文を生成
        # ...
```

#### `services/research/perplexity_client.py`

```python
"""Perplexity API クライアント（リサーチ）"""

class PerplexityClient(IResearcher):
    """Perplexity APIを使用したリサーチクライアント"""
    
    def __init__(self, config: Config):
        # ...
    
    async def research(self, theme: str, mode: str) -> ResearchResult:
        """テーマをリサーチ"""
        # 5つのモード: debate/voices/trivia/weekly_digest/lecture
        # ...
```

#### `services/audio_synthesis/voicevox_client.py`

```python
"""VOICEVOX API クライアント（音声合成）"""

class VoicevoxClient(IAudioSynthesizer):
    """VOICEVOX APIを使用した音声合成クライアント"""
    
    async def synthesize_dialogue(
        self,
        script: Script,
        output_dir: Path,
        # ...
    ) -> AudioSynthesisResult:
        """台本から音声を合成"""
        # 1. 各セリフを音声合成
        # 2. 音声ファイルを結合
        # 3. 字幕ファイル生成 (ASS形式)
        # 4. チャプターマーカー生成
        # ...
```

#### `services/video_rendering/ffmpeg_renderer.py`

```python
"""FFmpeg ラッパー（動画レンダリング）"""

class FfmpegRenderer:
    """FFmpegを使用した動画レンダリング"""
    
    def render_video(
        self,
        audio_path: Path,
        background_path: Path,
        subtitle_path: Path,
        output_path: Path,
        # ...
    ) -> VideoRenderResult:
        """動画をレンダリング"""
        # FFmpegコマンド構築・実行
        # - 背景画像
        # - 音声トラック
        # - BGM（フェードイン・フェードアウト）
        # - 字幕（ASS形式）
        # - 音声スペクトラム可視化
        # ...
```

#### `services/media_processing/thumbnail_generator.py`

```python
"""サムネイル画像生成"""

class ThumbnailGenerator:
    """サムネイル画像を生成"""
    
    def generate(
        self,
        title: str,
        background_path: Path,
        output_path: Path,
        thumbnail_title: str = "",
        # ...
    ) -> Path:
        """サムネイル画像を生成"""
        # 1. 背景画像読み込み・リサイズ (1280x720)
        # 2. 背景を暗くしてブラー
        # 3. タイトルテキスト描画（中央）
        # 4. 日付バッジ描画（右上）
        # センターセーフ方式で1:1トリミング対応
        # ...
    
    def _draw_title_text(self, img: Image.Image, title: str) -> Image.Image:
        """タイトルテキストを描画（中央）"""
        # AI生成のthumbnail_titleを使用
        # ...
    
    def _draw_date_badge(self, img: Image.Image) -> Image.Image:
        """日付バッジを描画（右上）"""
        # "YYYY.MM.DD制作" 形式
        # ...
```

---

### 3.4 Core Utilities

#### `core/prompt_manager.py`

```python
"""プロンプトテンプレート管理"""

class PromptManager:
    """プロンプトテンプレートを管理"""
    
    def __init__(self, prompts_path: Path):
        # config/prompts.yaml を読み込み
        # ...
    
    def get_script_prompt(self, mode: str, title_prefix: str = "") -> str:
        """台本生成プロンプトを取得"""
        # ...
    
    def get_packaging_prompt(self) -> str:
        """パッケージングプロンプトを取得"""
        # メタデータ生成用
        # ...
```

#### `core/settings_manager.py`

```python
"""ユーザー設定の永続化"""

class SettingsManager:
    """ユーザー設定を管理"""
    
    def load(self) -> dict:
        """設定を読み込み"""
        # user_settings.json から読み込み
        # ...
    
    def save(self, settings: dict) -> None:
        """設定を保存"""
        # user_settings.json に保存
        # ...
```

---

## 4. Current Status & Issues

### 4.1 Latest Changes (v3.1.1 - JSON Mode)

**Branch:** `fix/smart-json-parsing`

**Key Improvements:**
1. ✅ **Native JSON Mode Enabled**
   - Added `response_mime_type="application/json"` to Gemini API calls
   - Removed ~30 lines of regex-based JSON extraction logic
   - Simplified error handling (no more markdown block parsing)
   - Direct `json.loads()` parsing for reliability

2. ✅ **Code Simplification**
   - `gemini_client.py`: Removed complex `_parse_response` logic
   - `workflow.py`: Removed regex patterns in `_generate_youtube_metadata`
   - Cleaner, more maintainable codebase

**Files Modified:**
- `services/script_generation/gemini_client.py`
- `workflow.py`
- `app.py` (version bump to v3.1.1)
- `README.md` (added v3.1.1 features)

### 4.2 Recent Version History

**v3.1 (Phase 2):**
- 🏷 Automated Metadata: AI-generated title, description, thumbnail text
- 📜 High-Density Script: 50+ phrase generation logic
- 🎨 Modern UI: Tab-based interface with settings persistence
- 🛡️ Stability: Improved error handling and theme inheritance

**v3.0 (Phase 1):**
- Tab-based UI: Auto-generation vs Manual workflow separation
- Manual workflow: Step A (Script) → Step B (Audio) → Step C (Video)
- Settings persistence: `user_settings.json`
- Processing logs: Detailed execution logs per run

### 4.3 Known Issues & TODOs

**No Critical Issues** ✅

**Potential Improvements:**
1. **Performance Optimization**
   - Consider caching Gemini API responses for similar themes
   - Parallel audio synthesis for multiple speakers

2. **Feature Enhancements**
   - Add more research modes (e.g., "comparison", "timeline")
   - Support for custom voice models beyond VOICEVOX
   - Multi-language support (currently Japanese-only)

3. **Testing**
   - Add unit tests for core models
   - Integration tests for API clients
   - End-to-end workflow tests

### 4.4 Dependencies Status

**External Dependencies:**
- ✅ VOICEVOX Engine: Must be running on `http://localhost:50021`
- ✅ FFmpeg: Must be installed and available in PATH
- ✅ Gemini API: Requires valid `GEMINI_API_KEY`
- ✅ Perplexity API: Requires valid `PERPLEXITY_API_KEY`

**Python Environment:**
- Python 3.10+ required
- All dependencies in `requirements.txt` are stable versions

### 4.5 Output Structure

**Generated Files per Execution:**
```
output/YYYYMMDD_HHMMSS/
├── research.json           # Raw research data
├── research_report.md      # Formatted research report
├── script.json             # Generated script (JSON)
├── video_metadata.json     # AI-generated metadata
├── metadata.txt            # YouTube metadata (formatted)
├── thumbnail.png           # Thumbnail image (1280x720)
├── processing_log.txt      # Execution log
├── audio/
│   ├── combined_audio.wav  # Final audio track
│   └── subtitles.ass       # Subtitle file (ASS format)
└── videos/
    └── radio_*.mp4         # Final video output
```

---

## 5. Architecture Overview

### 5.1 Workflow Pipeline

```
User Input (Theme)
    ↓
[1] Research Phase (Perplexity API)
    ↓
[2] Script Generation (Gemini API + JSON Mode)
    ↓
[3] Audio Synthesis (VOICEVOX)
    ↓
[4] Video Rendering (FFmpeg)
    ↓
[5] Thumbnail Generation (Pillow)
    ↓
[6] Metadata Packaging (Gemini API + JSON Mode)
    ↓
Final Output (MP4 + Metadata)
```

### 5.2 Key Design Patterns

1. **Interface-Based Architecture**
   - `IScriptGenerator`, `IResearcher`, `IAudioSynthesizer`
   - Easy to swap implementations (e.g., Gemini ↔ Claude)

2. **Configuration-Driven**
   - All settings in `config.yaml`
   - Environment variables for secrets (`.env`)

3. **Pydantic Models**
   - Type-safe data validation
   - Automatic JSON serialization/deserialization

4. **Async/Await**
   - Non-blocking API calls
   - Efficient I/O operations

5. **Rich Console Output**
   - Beautiful CLI feedback
   - Progress indicators for long operations

---

## 6. Next Steps & Recommendations

### For Design/Requirements AI:

1. **Review Current Architecture**
   - Validate the interface-based design
   - Suggest improvements for scalability

2. **Feature Prioritization**
   - Evaluate potential new features (see 4.3)
   - Define requirements for next phase (v3.2?)

3. **Testing Strategy**
   - Define test coverage goals
   - Specify integration test scenarios

4. **Documentation**
   - API documentation (docstrings → Sphinx?)
   - User guide for manual workflow

5. **Performance Benchmarks**
   - Define acceptable execution times
   - Identify bottlenecks for optimization

---

## 7. Contact & Support

**Project Repository:** (Not specified)  
**Tech Lead:** AI Assistant (Cascade)  
**Current Branch:** `fix/smart-json-parsing`  
**Last Updated:** 2026-02-05

---

**End of Report**
