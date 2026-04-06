# プロジェクト現況レポート
**生成日時**: 2026-04-04  
**プロジェクト名**: 自動ラジオ動画生成システム v3.6  
**対象読者**: 設計・要件定義担当AI (Gemini/ChatGPT等)

---

## 1. Directory Structure

```
auto_radio_generator/
├── app.py                          # Web UI エントリーポイント (Gradio)
├── app_hitl.py                     # HITL モード UI コンポーネント
├── app_hitl_handlers.py            # HITL モード イベントハンドラ
├── main.py                         # CLI エントリーポイント
├── workflow.py                     # 共通ワークフロー (CLI/Web UI共通)
├── config.yaml                     # 設定ファイル (リサーチ/台本/音声/動画)
├── requirements.txt                # Python依存パッケージ
├── .env.example                    # 環境変数テンプレート
├── .gitignore                      # Git除外設定
├── README.md                       # プロジェクト説明書
├── user_settings.json              # ユーザー設定 (自動生成)
├── check_speakers.py               # VOICEVOX話者確認ユーティリティ
├── test_visual_fix.py              # 視覚的修正検証スクリプト
├── run.bat                         # CLI実行バッチ
├── run_webui.bat                   # Web UI実行バッチ
│
├── core/                           # ドメイン層
│   ├── __init__.py
│   ├── settings_manager.py         # 設定永続化マネージャー
│   ├── session_manager.py          # セッション管理（workspace/配下のI/O）
│   ├── prompt_manager.py           # プロンプトテンプレート管理
│   ├── interfaces/                 # 抽象インターフェース (ABC)
│   │   ├── __init__.py
│   │   ├── researcher.py           # IResearcher (リサーチャーIF)
│   │   ├── script_generator.py     # IScriptGenerator (台本生成IF)
│   │   ├── audio_synthesizer.py    # IAudioSynthesizer (音声合成IF)
│   │   └── video_renderer.py       # IVideoRenderer (動画生成IF)
│   └── models/                     # Pydanticデータモデル
│       ├── __init__.py
│       ├── config.py               # AppConfig (設定モデル)
│       ├── script.py               # Script, DialogueLine, RadioScriptArtifact
│       ├── artifacts.py            # ResearchBrief (中間成果物モデル)
│       ├── research.py             # ResearchResult, ResearchPlan
│       ├── visual.py               # VisualIdentity, VisualPalette
│       └── usage.py                # 使用量・コストモデル
│
├── services/                       # アプリケーション層
│   ├── __init__.py
│   ├── cost_calculator.py          # コスト計算サービス
│   ├── pipeline/                   # フェーズ分離パイプライン
│   │   ├── __init__.py
│   │   ├── research_phase.py       # リサーチフェーズ実行
│   │   ├── scripting_phase.py      # 台本作成フェーズ実行
│   │   └── production_phase.py     # 動画生成フェーズ実行
│   ├── research/                   # リサーチサービス
│   │   ├── __init__.py
│   │   └── perplexity_client.py    # Perplexity API実装
│   ├── script_generation/          # 台本生成サービス
│   │   ├── __init__.py
│   │   ├── gemini_client.py        # Gemini API実装
│   │   ├── lecture_prompt.py       # 講座モード専用プロンプト
│   │   └── time_expressions.py     # モード別時間表現定義
│   ├── audio_synthesis/            # 音声合成サービス
│   │   ├── __init__.py
│   │   └── voicevox_client.py      # VOICEVOX API実装
│   ├── video_rendering/            # 動画生成サービス
│   │   ├── __init__.py
│   │   └── ffmpeg_renderer.py      # FFmpeg実装
│   └── media_processing/           # メディア処理
│       ├── __init__.py
│       └── thumbnail_generator.py  # サムネイル生成
│
├── assets/                         # 静的リソース
│   ├── backgrounds/                # 背景画像 (20枚以上)
│   │   └── *.png
│   └── bgm/                        # BGM音楽 (16曲以上)
│       └── *.mp3
│
├── workspace/                      # セッションワークスペース (gitignore)
│   └── YYYYMMDD_HHMMSS/            # セッション単位のディレクトリ
│       ├── research_brief.json     # リサーチ結果
│       ├── script.json             # 台本データ
│       ├── audio.wav               # 音声ファイル
│       ├── subtitle.ass            # 字幕ファイル
│       └── videos/                 # 動画出力
│
└── output/                         # 生成物（レガシー）
    ├── YYYYMMDD_HHMMSS/            # 自動生成モード
    └── manual_builds/              # マニュアル制作モード
```

---

## 2. Environment & Dependencies

### 2.1 環境変数 (`.env.example`)

```env
# Perplexity API Key (https://www.perplexity.ai/)
PERPLEXITY_API_KEY=pplx-********************************

# Google Gemini API Key (https://aistudio.google.com/)
GEMINI_API_KEY=AIzaSy*************************************

# VOICEVOX Engine URL (ローカルで起動している場合)
VOICEVOX_BASE_URL=http://localhost:50021
```

### 2.2 依存パッケージ (`requirements.txt`)

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

### 2.3 設定ファイル (`config.yaml` - 抜粋)

```yaml
# リサーチ設定（Perplexity API）
researcher:
  model: "sonar-reasoning-pro"
  max_tokens: 8192
  modes:
    debate: { name: "ディベート", description: "賛成・反対の両論を調査" }
    voices: { name: "世間の声", description: "SNSの反応や一般意見を収集" }
    trivia: { name: "トリビア", description: "あまり知られていない事実を調査" }
    weekly_digest: { name: "今週のまとめ", description: "直近1週間のニュースをトップ3選定" }
    lecture: { name: "解説・講座", description: "初心者向けに比喩を使って解説" }

# 台本生成エンジン設定（Gemini API）
script_generator:
  gemini:
    model: "gemini-3.0-pro"
    fallback_model: "gemini-2.5-pro"
    max_tokens: 8192
  structure:
    main_topic_ratio: 70
    listener_mail_ratio: 20
    ending_ratio: 10

# 音声合成設定（VOICEVOX）
audio_synthesizer:
  speakers:
    main: 3  # ずんだもん
    sub: 2   # 四国めたん
  speed_scale: 1.1
  pause_between_phrases_ms: 500

# 動画生成設定（FFmpeg）
video_renderer:
  output_resolution: "1920x1080"
  output_fps: 30
  bgm_volume: 0.15
  enable_spectrum: true

# パーソナリティ設定
personalities:
  main:
    name: "ずんだもん"
    description: "語尾は『〜なのだ』。好奇心旺盛だが少し抜けている。"
  sub:
    name: "めたん"
    description: "語尾は『〜わよ』『〜かしら』。冷静沈着なお嬢様。"
```

---

## 3. Implementation Skeleton (Key Files)

### 3.1 エントリーポイント

#### `app.py` (Web UI)

```python
"""自動ラジオ動画生成システム - Gradio Web UI

v3.0 機能:
- タブ式UI: 自動生成とマニュアル制作を分離
- マニュアル制作ワークフロー: Step A(台本) → Step B(音声) → Step C(動画)
- 設定の永続化: ユーザー設定を自動保存・復元
"""
import gradio as gr
from workflow import run_workflow_sync, WorkflowResult
from core.settings_manager import SettingsManager

# リサーチモードのマッピング
RESEARCH_MODE_MAP = {
    "ディベート (賛否両論)": "debate",
    "世間の声 (SNS反応)": "voices",
    "トリビア (雑学)": "trivia",
    "今週のまとめ (ニュース)": "weekly_digest",
    "解説・講座 (Lecture)": "lecture",
    "リサーチなし": None
}

def generate_video(
    theme: str,
    research_mode: str,
    background_image: str,
    bgm_file: str,
    bgm_volume: float,
    fade_time: float,
    speed_scale: float,
    enable_spectrum: bool,
    progress=gr.Progress()
) -> tuple[str | None, str, str, str, str]:
    """動画生成を実行"""
    # ... ワークフロー実行ロジック

def create_ui() -> gr.Blocks:
    """Gradio UIを構築"""
    with gr.Blocks(title="自動ラジオ動画生成システム v3.6") as app:
        with gr.Tabs():
            # タブ1: 全自動モード
            with gr.Tab("🚀 全自動モード"):
                # テーマ入力のみで動画完成
                # ... UI定義
            
            # タブ2: HITLモード (Human-in-the-Loop)
            with gr.Tab("🎯 HITLモード"):
                # Gate 1: Research & Review
                # Gate 2: Script Generation & Editing
                # Gate 3: Production (Rendering)
                # ... UI定義
            
            # タブ3: ダッシュボード
            with gr.Tab("📊 ダッシュボード"):
                # ... UI定義
            
            # タブ4: 設定
            with gr.Tab("⚙️ 設定"):
                # ... UI定義
    
    return app

if __name__ == "__main__":
    app = create_ui()
    app.launch(server_name="127.0.0.1", server_port=7861)
```

#### `workflow.py` (共通ワークフロー)

```python
"""自動ラジオ動画生成システム - 共通ワークフロー関数"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass
class UIOverrides:
    """UIから渡されるパラメータのオーバーライド設定"""
    research_mode: Optional[ResearchMode] = None
    enable_research: bool = True
    bgm_volume: Optional[float] = None
    speed_scale: Optional[float] = None
    background_image: Optional[str] = None
    bgm_file: Optional[str] = None
    # ...

@dataclass
class WorkflowResult:
    """ワークフロー実行結果"""
    success: bool
    video_path: Optional[Path] = None
    script: Optional[Script] = None
    audio_path: Optional[Path] = None
    duration_sec: float = 0.0
    usage: Optional[TotalUsage] = None
    cost: Optional[CostBreakdown] = None
    # ...

async def run_workflow(
    theme: str,
    output_dir: Path,
    overrides: UIOverrides,
    callback: ProgressCallback
) -> WorkflowResult:
    """動画生成ワークフローを実行
    
    1. リサーチ (Perplexity)
    2. 台本生成 (Gemini)
    3. 音声合成 (VOICEVOX)
    4. 動画生成 (FFmpeg)
    5. サムネイル生成
    """
    # ... 実装

def run_workflow_sync(...) -> WorkflowResult:
    """同期版ワークフロー (Gradio用)"""
    return asyncio.run(run_workflow(...))
```

---

### 3.2 データモデル・型定義

#### `core/interfaces/researcher.py`

```python
"""リサーチャーインターフェース（ABC）"""
from abc import ABC, abstractmethod
from typing import Literal

ResearchMode = Literal["debate", "voices", "trivia", "weekly_digest", "lecture"]

@dataclass
class ResearchResult:
    """リサーチ結果"""
    topic: str
    mode: ResearchMode
    content: str
    sources: list[str] | None = None
    usage: "PerplexityUsage | None" = None

class IResearcher(ABC):
    """リサーチャーの抽象基底クラス"""
    
    @abstractmethod
    async def research(self, topic: str, mode: ResearchMode) -> ResearchResult:
        """テーマについてリサーチを実行する"""
        pass
    
    @abstractmethod
    async def check_api_status(self) -> bool:
        """APIの接続状態を確認する"""
        pass
```

#### `core/interfaces/script_generator.py`

```python
"""台本生成インターフェース"""
from abc import ABC, abstractmethod

class IScriptGenerator(ABC):
    """台本生成の抽象インターフェース"""
    
    @abstractmethod
    async def generate(
        self,
        theme: str,
        research_data: Optional["ResearchResult"] = None
    ) -> Script:
        """テーマに基づいて台本を生成する"""
        pass
```

#### `core/models/script.py`

```python
"""台本データモデル"""
from pydantic import BaseModel, Field
from typing import Literal, Optional

class DialogueLine(BaseModel):
    """対話の1行を表すモデル"""
    speaker_id: Literal["main", "sub"]
    text: str
    section: Optional[str] = None  # セクション名 (例: 'intro', 'news_1', 'ending')

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

---

### 3.3 主要なビジネスロジック

#### `services/research/perplexity_client.py`

```python
"""Perplexity APIを使用したリサーチクライアント"""
from openai import AsyncOpenAI
from core.interfaces import IResearcher, ResearchResult, ResearchMode

class PerplexityResearcher(IResearcher):
    """Perplexity APIを使用したリサーチャー実装"""
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.client = AsyncOpenAI(
            api_key=config.env.perplexity_api_key,
            base_url="https://api.perplexity.ai"
        )
        self.model = config.yaml.researcher.model
    
    async def research(self, topic: str, mode: ResearchMode) -> ResearchResult:
        """テーマについてリサーチを実行"""
        system_prompt = self._get_default_system_prompt(mode)
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Topic: {topic}"}
            ]
        )
        
        return ResearchResult(
            topic=topic,
            mode=mode,
            content=response.choices[0].message.content,
            sources=self._extract_citations(response),
            usage=self._extract_usage(response)
        )
    
    def _get_default_system_prompt(self, mode: ResearchMode) -> str:
        """モード別のシステムプロンプトを取得"""
        mode_specific = {
            "debate": "賛成・反対の両論を調査...",
            "voices": "SNSの反応や一般意見を収集...",
            "trivia": "あまり知られていない事実を調査...",
            "weekly_digest": "直近1週間のニュースをトップ3選定...",
            "lecture": "初心者向けに比喩を使って解説..."
        }
        return mode_specific.get(mode, "...")
```

#### `services/script_generation/gemini_client.py`

```python
"""Gemini APIを使用した台本生成クライアント"""
import google.genai as genai
from core.interfaces import IScriptGenerator, ResearchResult
from .lecture_prompt import build_lecture_prompt
from .time_expressions import get_time_expression

class GeminiClient(IScriptGenerator):
    """Gemini APIを使用した台本生成実装"""
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        genai.configure(api_key=config.env.gemini_api_key)
        self.model = config.yaml.script_generator.gemini.model
        self.personalities = config.yaml.personalities
    
    async def generate(
        self,
        theme: str,
        research_data: Optional[ResearchResult] = None
    ) -> Script:
        """テーマに基づいて台本を生成"""
        
        # モード別のプロンプト生成
        if research_data and research_data.mode == "weekly_digest":
            system_prompt = self._build_weekly_digest_prompt(theme)
        elif research_data and research_data.mode == "lecture":
            system_prompt = build_lecture_prompt(
                theme, self.personalities.main, self.personalities.sub
            )
        else:
            system_prompt = self._build_standard_prompt(theme, research_data)
        
        # Gemini API呼び出し
        response = await self._call_gemini_api(system_prompt, research_data)
        
        # JSONパース & Scriptモデル化
        script_dict = self._parse_json_response(response)
        return Script(**script_dict)
    
    def _build_weekly_digest_prompt(self, theme: str) -> str:
        """週次ダイジェスト専用プロンプト"""
        # 動的時間表現を使用
        time_expr = get_time_expression("weekly_digest")
        return f"""あなたは人気ニュース番組の台本作家です。
2人のキャスターによる「{time_expr['title_prefix']}ニュースまとめ」番組の台本を作成してください。
..."""
```

#### `services/script_generation/lecture_prompt.py`

```python
"""講座モード専用のプロンプト生成"""
from typing import Any

def build_lecture_prompt(theme: str, main_char: Any, sub_char: Any) -> str:
    """講座モード専用のシステムプロンプトを構築
    
    ずんだもん（生徒役）とめたん（先生役）による教育番組形式
    """
    return f"""あなたは教育番組の台本作家です。
初心者（{main_char.name}）に専門知識を分かりやすく教える「解説・講座」番組の台本を作成してください。

## キャラクター設定
### 生徒役（speaker_id: "main"）
- 名前: {main_char.name}
- 役割: 知識ゼロの初心者。素朴な疑問を投げかける。

### 先生役（speaker_id: "sub"）
- 名前: {sub_char.name}
- 役割: 優しく教えるお姉さん。比喩を使って噛み砕いて解説する。

## 番組構成（厳守）
### イントロ（ボケから入る）
### 本編: 3つのステップで解説
  - ステップ1: 基本の定義
  - ステップ2: 比喩で理解
  - ステップ3: 具体例と活用
### エンディング

## セクションマーカー（重要）
- "intro" - オープニング
- "definition" - 基本定義
- "metaphor" - 比喩説明
- "example" - 具体例
- "ending" - エンディング
..."""
```

#### `services/audio_synthesis/voicevox_client.py`

```python
"""VOICEVOX APIを使用した音声合成クライアント"""
import httpx
from pydub import AudioSegment
from core.interfaces import IAudioSynthesizer, SynthesisResult, ChapterMarker

class VoicevoxClient(IAudioSynthesizer):
    """VOICEVOX Local APIを使用した音声合成"""
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.base_url = config.env.voicevox_base_url
        self.speakers = config.yaml.audio_synthesizer.speakers
    
    async def synthesize(
        self,
        script: Script,
        output_dir: Path,
        speed_scale_override: Optional[float] = None
    ) -> SynthesisResult:
        """台本から音声を合成"""
        
        phrase_data = []
        chapters: list[ChapterMarker] = []
        current_time_ms = 0
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            for i, line in enumerate(script.dialogue):
                # セクション開始を検出してチャプターを記録
                if line.section:
                    chapter_title = self._get_chapter_title(line.section, line.text)
                    chapters.append(ChapterMarker(
                        start_time_sec=(current_time_ms / 1000.0) + 2.0,
                        title=chapter_title,
                        section_id=line.section
                    ))
                
                # 音声合成
                audio_data = await self._synthesize_phrase(
                    client, line.text, speaker_id, speed_scale
                )
                audio_segment = AudioSegment.from_wav(BytesIO(audio_data))
                phrase_data.append((audio_segment, current_time_ms, ...))
                current_time_ms += len(audio_segment) + pause_ms
        
        # 音声結合 & 字幕生成
        combined_audio = self._combine_audio(phrase_data, pause_ms)
        self._generate_ass(phrase_data, subtitle_path)
        
        return SynthesisResult(
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            total_duration_sec=total_duration_sec,
            chapters=chapters
        )
    
    def _get_chapter_title(self, section_id: str, text: str) -> str:
        """セクションIDからチャプタータイトルを生成"""
        section_titles = {
            "intro": "オープニング",
            "main": "本題",
            "news_1": "ニュース1",
            "news_2": "ニュース2",
            "news_3": "ニュース3",
            "listener_mail": "リスナーメール",
            "ending": "エンディング",
            # Lecture mode sections
            "definition": "基本の定義",
            "metaphor": "比喩で理解",
            "example": "具体例と活用",
        }
        return section_titles.get(section_id, section_id)
```

#### `services/video_rendering/ffmpeg_renderer.py`

```python
"""FFmpegを使用した動画レンダリングクライアント"""
import subprocess
from pathlib import Path
from core.interfaces import IVideoRenderer, RenderResult, ChapterMarker

class FfmpegRenderer(IVideoRenderer):
    """FFmpegを使用した動画生成実装"""
    
    async def render(
        self,
        audio_path: Path,
        subtitle_path: Path,
        background_image: Path,
        bgm_path: Path,
        output_path: Path,
        chapters: list[ChapterMarker] = []
    ) -> RenderResult:
        """動画を生成"""
        
        # FFmpegコマンド構築
        ffmpeg_cmd = self._build_ffmpeg_command(
            audio_path, subtitle_path, background_image,
            bgm_path, output_path
        )
        
        # FFmpeg実行
        process = subprocess.run(ffmpeg_cmd, capture_output=True)
        
        # YouTubeチャプター生成
        chapter_text = self._generate_youtube_chapters(chapters)
        
        return RenderResult(
            video_path=output_path,
            file_size_mb=output_path.stat().st_size / (1024 * 1024),
            chapters=chapter_text
        )
    
    def _generate_youtube_chapters(self, chapters: list[ChapterMarker]) -> str:
        """YouTubeチャプター形式のテキストを生成"""
        lines = []
        for chapter in chapters:
            timestamp = self._format_timestamp(chapter.start_time_sec)
            lines.append(f"{timestamp} {chapter.title}")
        return "\n".join(lines)
```

---

## 4. Current Status & Issues

### 4.1 最近の変更履歴

#### ✅ 完了した機能追加 (2026-01-16)

1. **講座モード (lecture) の追加**
   - 初心者向け解説番組形式を新規実装
   - 先生（めたん）と生徒（ずんだもん）の対話形式
   - 比喩を使った分かりやすい解説に特化
   - ファイル: `services/script_generation/lecture_prompt.py`

2. **時間表現の動的化**
   - 週次ダイジェストの「今週の」を「最近の」に柔軟化
   - モード別の時間表現を一元管理
   - ファイル: `services/script_generation/time_expressions.py`

3. **YouTubeチャプター機能の強化**
   - セクションマーカーから自動的にチャプター生成
   - 講座モード用のチャプタータイトルマッピング追加
   - ファイル: `services/audio_synthesis/voicevox_client.py`

4. **ドキュメント整備**
   - README.md: 5つのリサーチモード、リサーチモード比較表を追加
   - config.yaml: 講座モードのドキュメント追加
   - コードクリーンアップ: type hints追加、PEP 8準拠

#### 📝 コミット履歴
```
fed212e - Refactor: Code cleanup and docs update (2026-01-16)
  - README.md: 講座モード追加、リサーチモード比較表追加
  - config.yaml: 講座モード設定追加
  - lecture_prompt.py: type hints追加
  - time_expressions.py: ドキュメント更新
```

---

### 4.2 現在の課題・TODO

#### 🔴 Critical Issues
**なし** - 現在、システムは安定稼働中

#### 🟡 Known Issues

1. **講座モードのチャプタータイトル問題 (部分的に解決済み)**
   - **問題**: 講座モードで生成される台本のチャプター名が `definition`, `metaphor`, `example` といった抽象的な英語のままになる
   - **原因**: `lecture_prompt.py` のプロンプトが構造名をそのまま `section` に使用するよう指示している
   - **対応状況**: 
     - ✅ `voicevox_client.py` に日本語マッピング追加済み（「基本の定義」「比喩で理解」「具体例と活用」）
     - ⚠️ 根本的な解決には、プロンプトを修正して具体的な日本語タイトルを生成させる必要あり
   - **次のステップ**: `lecture_prompt.py` の97-103行目を修正し、具体的な内容を表す日本語タイトルを要求する

2. **Gemini APIモデル名の不整合**
   - `config.yaml` に `gemini-3.0-pro` と記載されているが、実際のモデル名は `gemini-2.0-flash-exp` などの可能性
   - 動作確認が必要

#### 🟢 Enhancement Ideas

1. **マニュアル制作モードの拡充**
   - 現在: Step A (台本) → Step B (音声) → Step C (動画)
   - 提案: 各ステップでのプレビュー機能追加

2. **コスト最適化**
   - Perplexity API の使用量削減オプション
   - Gemini のフォールバックモデル活用

3. **テスト自動化**
   - 単体テスト未整備
   - E2Eテストの追加

---

### 4.3 技術的負債

1. **型安全性の向上**
   - 一部のファイルで `Any` 型を使用（例: `lecture_prompt.py`）
   - Pydanticモデルの活用をさらに拡大

2. **エラーハンドリングの統一**
   - 各サービスで独自のエラーハンドリング
   - 共通の例外クラス導入を検討

3. **ログ出力の標準化**
   - `rich.console` と標準ログの混在
   - 構造化ログへの移行を検討

---

### 4.4 外部依存関係

#### 必須の外部ツール
1. **VOICEVOX Engine** (v0.24.0+)
   - ローカルで起動が必要
   - URL: http://localhost:50021
   - ダウンロード: https://voicevox.hiroshiba.jp/

2. **FFmpeg** (v4.0+)
   - システムPATHに追加が必要
   - ダウンロード: https://ffmpeg.org/

#### API依存関係
1. **Perplexity API**
   - モデル: `sonar-reasoning-pro`
   - 用途: テーマのリサーチ
   - レート制限: 要確認

2. **Google Gemini API**
   - モデル: `gemini-3.0-pro` (要確認)
   - 用途: 台本生成
   - レート制限: 要確認

---

## 5. Architecture Overview

### 5.1 設計パターン

- **レイヤードアーキテクチャ**: Core (ドメイン層) / Services (アプリケーション層)
- **依存性逆転の原則**: 抽象インターフェース (ABC) を使用
- **データクラス**: Pydantic BaseModel で型安全性を確保

### 5.2 データフロー

```
[User Input (Web UI/CLI)]
    ↓
[Workflow Orchestrator]
    ↓
[1. Research] → Perplexity API → ResearchResult
    ↓
[2. Script Generation] → Gemini API → Script
    ↓
[3. Audio Synthesis] → VOICEVOX API → SynthesisResult (audio + subtitles + chapters)
    ↓
[4. Video Rendering] → FFmpeg → RenderResult (video + chapters)
    ↓
[5. Thumbnail Generation] → Pillow → thumbnail.png
    ↓
[Output Files]
```

### 5.3 拡張性

- **新しいAIエンジンの追加**: 抽象インターフェースを継承して実装
  - 例: `OpenAIScriptGenerator(IScriptGenerator)`
  - 例: `ElevenLabsAudioSynthesizer(IAudioSynthesizer)`

- **新しいリサーチモードの追加**:
  1. `core/interfaces/researcher.py` の `ResearchMode` に追加
  2. `config.yaml` の `researcher.modes` に定義追加
  3. `services/research/perplexity_client.py` にプロンプト追加

---

## 6. Summary

### プロジェクトの現状
- **バージョン**: v3.0 (安定版)
- **主要機能**: 5つのリサーチモード、3つの台本形式、音声合成、動画生成、YouTubeチャプター対応
- **技術スタック**: Python 3.10+, Gradio, Pydantic, VOICEVOX, FFmpeg
- **開発状況**: 基本機能は完成、講座モードのチャプタータイトル改善が残課題

### 次のマイルストーン候補
1. 講座モードのチャプタータイトル生成を根本的に改善
2. マニュアル制作モードのプレビュー機能追加
3. テスト自動化の導入
4. パフォーマンス最適化（API呼び出しの並列化）

---

**レポート作成者**: Cascade AI (Tech Lead)  
**対象読者**: 設計・要件定義担当AI (Gemini/ChatGPT等)  
**更新日**: 2026-01-16
