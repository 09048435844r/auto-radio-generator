# プロジェクト現況レポート

**作成日**: 2026-03-20  
**対象**: 設計・要件定義担当AI  
**プロジェクト**: 自動ラジオ動画生成システム v3.3.2

> ⚠️ **現行実装との差分ノート（2026-04-18 追記）**
>
> 本ドキュメントは設計時点のスケッチであり、コード例には現行実装と食い違う箇所があります。特にコスト計算周りについては下記の差分を参照してください。
>
> - **料金データの保存場所**: `config/costs.yaml` は廃止され、全てのレートおよび `usd_to_jpy` は `config.yaml > script_generator.*` に統合されています（SSOT）。
> - **`CostCalculator` のシグネチャ**:
>   - 旧スケッチ: `CostCalculator(costs_yaml_path)` + `calculate_llm_cost(usage)`
>   - 現行実装: `CostCalculator(config: AppConfig)` + `get_llm_rate(provider: str, model_name: str)`
> - **プロバイダ推論の廃止**: モデル名からプロバイダを推論する `_get_provider_from_model_name` は削除されました。呼び出し側は `provider` を明示的に渡す必要があります。
> - **未登録モデルのフォールバック警告**: 当該プロバイダの先頭モデル単価にフォールバックした場合、`logger.warning` で通知されます。
> - **Free Tier 判定**: `request_count <= 1` から `1 <= request_count <= 1` に厳格化されました（未使用=0 を誤検知しない）。
> - **JPY 換算の SSOT 統一**: `comparison_report.py` の `cost_usd * 150.0` ハードコードは廃止され、`calculator.usd_to_jpy` を参照しています。
>
> 詳細は `CHANGELOG.md` の 2026-04-18 エントリおよび `docs/MULTI_LLM_GUIDE.md > コスト計算API` を参照してください。

---

## 1. Directory Structure

```
auto_radio_generator/
├── app.py                          # Gradio WebUI（メインエントリーポイント）
├── workflow.py                     # 動画生成ワークフロー（CLI版）
├── main.py                         # CLIエントリーポイント
├── requirements.txt                # Python依存関係
├── config.yaml                     # アプリケーション設定
├── .env.example                    # 環境変数テンプレート
│
├── config/
│   └── costs.yaml                  # API料金設定（動的コスト計算用）
│
├── core/                           # コアモデル・インターフェース
│   ├── interfaces.py               # 抽象インターフェース定義
│   ├── models/
│   │   ├── config.py               # 設定モデル（Pydantic）
│   │   ├── script.py               # 台本データモデル
│   │   ├── research.py             # リサーチ結果モデル
│   │   └── llm_usage.py            # LLM使用量モデル
│   └── prompt_manager.py           # プロンプトテンプレート管理
│
├── services/                       # ビジネスロジック層
│   ├── research.py                 # Perplexity リサーチサービス
│   ├── cost_calculator.py          # APIコスト計算サービス
│   ├── comparison_report.py        # LLMモデル比較レポート生成
│   │
│   ├── script_generation/          # 台本生成サービス
│   │   ├── llm_factory.py          # LLMクライアント ファクトリ
│   │   ├── gemini_client.py        # Gemini API クライアント
│   │   ├── openai_client.py        # OpenAI API クライアント
│   │   ├── anthropic_client.py     # Anthropic API クライアント
│   │   └── time_expressions.py     # 時刻表現生成
│   │
│   ├── audio/                      # 音声合成サービス
│   │   ├── voicevox_client.py      # VOICEVOX API クライアント
│   │   └── audio_processor.py      # 音声ファイル処理
│   │
│   ├── video/                      # 動画生成サービス
│   │   ├── ffmpeg_renderer.py      # FFmpeg 動画レンダリング
│   │   └── subtitle_generator.py   # 字幕ファイル生成（.ass）
│   │
│   ├── thumbnail/                  # サムネイル生成サービス
│   │   └── thumbnail_generator.py  # Pillow + BudouX サムネイル生成
│   │
│   └── publishing/                 # YouTube公開サービス
│       ├── youtube_uploader.py     # YouTube Data API v3 アップロード
│       └── metadata_builder.py     # メタデータ（タイトル・説明・タグ）生成
│
├── assets/                         # 静的アセット
│   ├── backgrounds/                # 背景画像
│   ├── bgm/                        # BGM音声ファイル
│   └── fonts/                      # フォント（サムネイル用）
│
├── data/                           # 実行時データ
│   └── research/                   # リサーチ結果保存（JSONL）
│
├── logs/                           # ログファイル
│   ├── execution_record_*.jsonl    # 実行履歴
│   └── cost_history_*.jsonl        # コスト履歴
│
├── output/                         # 生成動画出力先
│
├── tests/                          # テストコード
│   ├── mock_data/                  # Mockモード用テストデータ
│   └── test_*.py                   # 単体テスト
│
└── docs/                           # ドキュメント
    ├── ui_refactoring_plan.md      # UI改善計画
    └── *.md                        # 各種ドキュメント
```

---

## 2. Environment & Dependencies

### 2.1 依存関係ファイル

#### `requirements.txt`

```txt
# Configuration & Validation
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
PyYAML>=6.0.0

# AI APIs
google-genai>=1.0.0      # Gemini API
openai>=1.0.0            # OpenAI API & Perplexity API
anthropic>=0.18.0        # Anthropic API

# Audio Processing
pydub>=0.25.1
numpy>=1.24.0

# Image Processing
Pillow>=10.0.0
budoux>=0.6.0

# HTTP Client
httpx>=0.27.0
requests>=2.31.0
beautifulsoup4>=4.12.0
chardet>=5.0.0

# CLI & Utilities
rich>=13.0.0

# Web UI
gradio>=4.0.0
pandas>=2.0.0
plotly>=5.0.0

# Publishing (YouTube Data API)
google-api-python-client>=2.0.0
google-auth-oauthlib>=1.0.0
google-auth-httplib2>=0.2.0

# Development & Testing
pytest>=9.0.0
pytest-mock>=3.15.0

# External Dependencies (要手動インストール):
# - VOICEVOX Engine: https://voicevox.hiroshiba.jp/
# - FFmpeg: https://ffmpeg.org/
```

### 2.2 環境変数設定

#### `.env.example`

```bash
# Perplexity API Key
PERPLEXITY_API_KEY=pplx-***

# Google Gemini API Key
GEMINI_API_KEY=AIzaSy***

# OpenAI API Key
OPENAI_API_KEY=sk-***

# Anthropic API Key
ANTHROPIC_API_KEY=sk-ant-***

# VOICEVOX Engine URL
VOICEVOX_BASE_URL=http://localhost:50021
```

### 2.3 主要設定ファイル

#### `config.yaml` (抜粋)

```yaml
# リサーチ設定（Perplexity API）
researcher:
  model: "sonar-reasoning-pro"
  max_tokens: 8192
  max_queries_per_plan: 3
  modes:
    debate: {...}
    voices: {...}
    trivia: {...}
    weekly_digest: {...}
    lecture: {...}

# 台本生成エンジン設定
script_generator:
  default_provider: "gemini"
  gemini:
    model: "gemini-3.1-pro-preview"
    fallback_model: "gemini-2.5-pro"
    flash_model: "gemini-2.5-flash"
    max_tokens: 16384
  openai:
    model: "gpt-5.4"
    fallback_model: "gpt-5.4-mini"
  anthropic:
    model: "claude-sonnet-4.6"
    fallback_model: "claude-haiku-4-5-20251001"

# 音声合成設定（VOICEVOX）
audio_synthesizer:
  speakers:
    main: 3  # ずんだもん
    sub: 2   # 四国めたん
  speed_scale: 1.1

# 動画生成設定（FFmpeg）
video_renderer:
  output_resolution: "1920x1080"
  output_fps: 30
  use_gpu: true  # NVENC GPU加速
  bgm_volume: 0.15
  enable_spectrum: true

# パーソナリティ設定
personalities:
  main:
    name: "ずんだもん"
    description: "語尾は『〜なのだ』。好奇心旺盛..."
  sub:
    name: "めたん"
    description: "語尾は『〜わよ』『〜かしら』。冷静沈着..."
```

#### `config/costs.yaml` (抜粋)

```yaml
# Perplexity API (USD per 1M tokens)
perplexity:
  sonar-reasoning-pro:
    api_model: sonar-reasoning-pro
    input: 2.00
    output: 8.00

# LLM Models (USD per 1M tokens)
llm_models:
  gemini-3.1-pro:
    api_model: gemini-3.1-pro-preview
    input: 1.50
    output: 12.00
  gpt-5.4:
    api_model: gpt-5.4-2026-03-05
    input: 2.50
    output: 15.00
  claude-sonnet-4.6:
    api_model: claude-sonnet-4-6
    input: 3.00
    output: 15.00

# Currency conversion
currency:
  usd_to_jpy: 150.0
```

---

## 3. Implementation Skeleton (Key Files)

### 3.1 エントリーポイント

#### `app.py` (Gradio WebUI)

```python
"""Gradio WebUIアプリケーション"""
import gradio as gr
from pathlib import Path
from core.models.config import load_config

PROJECT_ROOT = Path(__file__).parent

# ========== UI作成関数 ==========
def create_generator_tab(saved_settings, assets: dict) -> dict:
    """動画生成タブのUI構築"""
    # 全自動モード
    with gr.Accordion("🚀 全自動モード", open=True):
        theme_input = gr.Textbox(label="テーマ", ...)
        research_mode_dropdown = gr.Dropdown(...)
        llm_provider_dropdown = gr.Dropdown(...)
        generate_btn = gr.Button("🚀 動画を生成する", ...)
        script_only_btn = gr.Button("📝 台本のみ作成", ...)
        research_only_btn = gr.Button("🔍 リサーチのみ実行", ...)  # ★新機能
    
    # こだわりステップモード
    step_components = create_step_mode_ui(assets)
    
    return {...}

def create_manual_tab(assets: dict) -> dict:
    """手動制作タブのUI構築"""
    # Step A: リサーチ結果から台本生成
    research_input = gr.Textbox(...)
    llm_model_manual = gr.Dropdown(...)  # ★LLMモデル選択
    comparison_state = gr.State(value=[])  # ★比較用State
    comparison_report = gr.Markdown(...)  # ★比較レポート
    
    # Step B: 音声合成
    # Step C: 動画レンダリング
    ...

def create_ui() -> gr.Blocks:
    """Gradio UIを作成"""
    with gr.Blocks(title="自動ラジオ動画生成システム v3.3.2") as app:
        with gr.Tabs():
            with gr.TabItem("🎬 動画生成", id="generator"):  # ★タブ名変更
                generator_components = create_generator_tab(...)
            with gr.TabItem("📊 ダッシュボード", id="dashboard"):
                dashboard_components = create_dashboard_tab()
            with gr.TabItem("⚙️ 設定", id="settings"):
                settings_components = create_settings_tab(...)
            with gr.TabItem("🛠️ 手動制作", id="manual"):
                manual_components = create_manual_tab(...)
        
        # イベントハンドラー登録
        generator_components["generate_btn"].click(
            fn=generate_video, inputs=[...], outputs=[...]
        )
        generator_components["research_only_btn"].click(  # ★新機能
            fn=research_only, inputs=[...], outputs=[...]
        )
        manual_components["generate_script_btn"].click(
            fn=generate_script_from_research, inputs=[...], outputs=[...]
        )
        ...
    
    return app

# ========== ビジネスロジック関数 ==========
def generate_video(theme, research_mode, llm_provider, ...) -> tuple:
    """動画を全自動生成"""
    # ...

def research_only(theme, research_mode, progress) -> tuple[str, str]:
    """リサーチのみを実行してJSONLファイルに保存"""
    # ★新機能: Phase 1で実装
    async def execute_research():
        script_generator = GeminiClient(config)
        plan = await script_generator.create_research_plan(...)
        researcher = PerplexityResearcher(config)
        research_result = await researcher.research_multi(...)
        return research_result, plan
    
    research_result, plan = asyncio.run(execute_research())
    
    # JSONL形式で保存
    filepath = research_dir / f"research_{timestamp}_{safe_theme}.jsonl"
    research_data = {
        "timestamp": ...,
        "theme": ...,
        "queries": plan.queries,
        "content": research_result.content,
        "sources": [{"url": s.url, "title": s.title} for s in research_result.sources]
    }
    with open(filepath, "w") as f:
        f.write(json.dumps(research_data, ensure_ascii=False) + "\n")
    
    return str(filepath), get_logs()

def generate_script_from_research(
    research_text, theme, model_name, comparison_state, progress
) -> tuple[str, str, str, list]:
    """リサーチ結果から台本を生成（LLMモデル比較対応）"""
    # ★Phase 1で実装: 非同期処理対応
    provider = get_provider_from_model_name(model_name)
    script_generator = create_script_generator(config, provider=provider)
    
    async def generate_async():
        return await script_generator.generate(theme, research_result)
    
    script = asyncio.run(generate_async())
    
    # コスト計算
    if hasattr(script_generator, 'last_usage'):
        calculator = CostCalculator()
        cost_lines = calculator.format_llm_cost_log(script_generator.last_usage)
    
    # 比較レポート生成
    updated_state = comparison_state + [{"model_name": model_name, ...}]
    if len(updated_state) >= 2:
        comparison_report_md = generate_comparison_report(updated_state)
    
    return script_json, script_json, comparison_report_md, updated_state

# ========== メイン実行 ==========
if __name__ == "__main__":
    app = create_ui()
    app.launch(server_name="127.0.0.1", server_port=7860)
```

---

### 3.2 データモデル

#### `core/models/config.py`

```python
"""設定モデル（Pydantic）"""
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

class EnvSettings(BaseSettings):
    """環境変数から読み込む設定"""
    perplexity_api_key: str = Field(default="", alias="PERPLEXITY_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    voicevox_base_url: str = Field(default="http://localhost:50021")

class ResearcherConfig(BaseModel):
    """リサーチャー（Perplexity）設定"""
    model: str = "sonar-reasoning-pro"
    max_tokens: int = 8192
    max_queries_per_plan: int = 3
    modes: Dict[str, ResearchModeConfig] = ...

class ScriptGeneratorConfig(BaseModel):
    """台本生成エンジン設定"""
    default_provider: str = "gemini"
    gemini: GeminiConfig = ...
    openai: OpenAIConfig = ...
    anthropic: AnthropicConfig = ...
    structure: ScriptStructureConfig = ...

class YamlConfig(BaseModel):
    """YAML設定ファイル全体"""
    researcher: ResearcherConfig = ...
    script_generator: ScriptGeneratorConfig = ...
    audio_synthesizer: AudioSynthesizerConfig = ...
    video_renderer: VideoRendererConfig = ...
    personalities: PersonalitiesConfig = ...
    dev: DevConfig = ...
    publishing: PublishingConfig = ...

class AppConfig(BaseModel):
    """アプリケーション全体の設定"""
    env: EnvSettings
    yaml: YamlConfig
    project_root: Path

def load_config(project_root: Path | str | None = None) -> AppConfig:
    """設定を読み込む"""
    env_settings = EnvSettings(_env_file=env_file)
    with open(yaml_path, "r") as f:
        yaml_data = yaml.safe_load(f)
    yaml_config = YamlConfig.model_validate(yaml_data)
    return AppConfig(env=env_settings, yaml=yaml_config, project_root=project_root)
```

#### `core/models/script.py`

```python
"""台本データモデル"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

SpeakerID = Literal["A", "B"]

class TurnType(str, Enum):
    """発話ターンの種別"""
    DIALOGUE = "dialogue"
    ACTION = "action"

class DialogueTurn(BaseModel):
    """台本の1行（会話ターンまたはアクション）"""
    speaker: Optional[SpeakerID] = None
    text: Optional[str] = None
    turn_type: TurnType = TurnType.DIALOGUE
    action_type: Optional[ActionType] = None
    action_path: Optional[str] = None
    section: Optional[str] = None
    chapter_title: Optional[str] = None
    
    def is_dialogue(self) -> bool: ...
    def is_action(self) -> bool: ...
    def is_jingle(self) -> bool: ...

class Script(BaseModel):
    """ラジオ台本全体"""
    title: str
    theme: str = ""
    sections: List[DialogueTurn] = Field(..., min_length=10)
    thumbnail_title: str
    description: Optional[str] = None
    hashtags: List[str] = []
    references: List[str] = []
    
    @property
    def dialogue(self) -> List[DialogueTurn]:
        """後方互換性のため"""
        return self.sections
```

---

### 3.3 主要サービス

#### `services/script_generation/llm_factory.py`

```python
"""LLMクライアント ファクトリ"""
from core.models.config import AppConfig
from core.interfaces import IScriptGenerator

def create_script_generator(
    config: AppConfig, provider: str = "gemini"
) -> IScriptGenerator:
    """プロバイダーに応じたLLMクライアントを生成"""
    if provider == "gemini":
        from .gemini_client import GeminiClient
        return GeminiClient(config)
    elif provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(config)
    elif provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(config)
    else:
        raise ValueError(f"Unknown provider: {provider}")

def get_provider_from_model_name(model_name: str) -> str:
    """モデル名からプロバイダー名を推定"""
    if model_name.startswith("gemini-"):
        return "gemini"
    elif model_name.startswith(("gpt-", "o1-", "o3-")):
        return "openai"
    elif model_name.startswith("claude-"):
        return "anthropic"
    else:
        raise ValueError(f"Unknown model name: {model_name}")

def get_available_models(config: AppConfig) -> list[str]:
    """利用可能なモデル一覧を取得"""
    # costs.yamlから動的に取得
    costs_path = config.project_root / "config" / "costs.yaml"
    with open(costs_path, "r") as f:
        costs_data = yaml.safe_load(f)
    
    available_providers = get_available_providers(config)
    models = []
    for model_name, model_config in costs_data["llm_models"].items():
        provider = get_provider_from_model_name(model_name)
        if provider in available_providers:
            models.append(model_name)
    
    return models
```

#### `services/cost_calculator.py`

```python
"""APIコスト計算サービス"""
from core.models.llm_usage import LLMUsage

class CostCalculator:
    """API使用量からコストを計算"""
    
    def __init__(self, costs_yaml_path: Path = None):
        """costs.yamlを読み込み"""
        with open(costs_yaml_path, "r") as f:
            self.costs_data = yaml.safe_load(f)
        self.usd_to_jpy = self.costs_data["currency"]["usd_to_jpy"]
    
    def calculate_llm_cost(self, usage: LLMUsage) -> tuple[float, float]:
        """LLM使用量からコストを計算（USD, JPY）"""
        model_costs = self.costs_data["llm_models"].get(usage.model_name)
        if not model_costs:
            return 0.0, 0.0
        
        input_cost = (usage.input_tokens / 1_000_000) * model_costs["input"]
        output_cost = (usage.output_tokens / 1_000_000) * model_costs["output"]
        total_usd = input_cost + output_cost
        total_jpy = total_usd * self.usd_to_jpy
        
        return total_usd, total_jpy
    
    def format_llm_cost_log(self, usage: LLMUsage) -> list[str]:
        """LLM使用量とコストをログ形式で整形"""
        cost_usd, cost_jpy = self.calculate_llm_cost(usage)
        return [
            f"📊 トークン使用量:",
            f"  入力: {usage.input_tokens:,} tokens",
            f"  出力: {usage.output_tokens:,} tokens",
            f"💰 コスト: ${cost_usd:.4f} (¥{cost_jpy:.2f})"
        ]
```

#### `services/comparison_report.py`

```python
"""LLMモデル比較レポート生成"""

def generate_comparison_report(scripts_data: List[dict]) -> str:
    """複数モデルの台本を比較したMarkdownレポートを生成"""
    if len(scripts_data) < 2:
        return "*比較には2つ以上のモデルが必要です*"
    
    # Markdown表を生成
    report = "## 📊 台本比較レポート\n\n"
    report += "| モデル | ターン数 | 推定動画長 | 入力トークン | 出力トークン | コスト (USD) |\n"
    report += "|--------|----------|------------|--------------|--------------|-------------|\n"
    
    for data in scripts_data:
        script_dict = json.loads(data["script_json"])
        usage = data["usage"]
        calculator = CostCalculator()
        cost_usd, _ = calculator.calculate_llm_cost(usage)
        
        turn_count = len(script_dict["dialogue"])
        estimated_duration = turn_count * 5  # 仮の推定
        
        report += f"| {data['model_name']} | {turn_count} | {estimated_duration}秒 | "
        report += f"{usage.input_tokens:,} | {usage.output_tokens:,} | ${cost_usd:.4f} |\n"
    
    return report
```

---

## 4. Current Status & Issues

### 4.1 直近の変更（2026-03-20）

#### ✅ 完了した実装

**Phase 1: UI改善 - リサーチのみモード追加 + タブ名変更**

1. **リサーチのみモード追加**
   - `research_only()` 関数を実装
   - 全自動モードに「🔍 リサーチのみ実行」ボタンを追加
   - リサーチ結果を `data/research/` に JSONL 形式で保存
   - タイムスタンプ付きファイル名で管理
   - **修正**: `ResearchSource` オブジェクトのJSONシリアライズエラーを解消

2. **タブ名の変更**
   - `Generator` → `🎬 動画生成`
   - `Dashboard` → `📊 ダッシュボード`
   - `Settings` → `⚙️ 設定`
   - `Manual` → `🛠️ 手動制作`

3. **LLMモデル比較機能**
   - 手動制作タブに「🤖 台本生成モデル」ドロップダウンを追加
   - `costs.yaml` から22種類のモデルを動的に取得
   - 複数モデルで台本生成時に比較レポートを自動生成
   - **修正**: `generate_script_from_research()` の非同期処理エラーを解消

4. **最新LLMモデル対応**
   - Gemini 2.5/3.1系、GPT-5系、o3系、Claude 4系を追加
   - `costs.yaml` に最新の料金情報を反映
   - `config.yaml` のデフォルトモデルを最新版に更新

#### 📋 実装済みコミット

```
f880a8a - 修正: 手動制作タブの台本生成で非同期処理エラーを解消
d72e052 - 修正: リサーチのみモードのJSONシリアライズエラーを解消
f97036b - 機能: Phase 1 UI改善 - リサーチのみモード追加 + タブ名変更
e8a236e - 設定: 最新LLMモデル価格情報に更新
```

---

### 4.2 現在発生している問題

#### ⚠️ 既知の警告

1. **urllib3 バージョン警告**
   ```
   RequestsDependencyWarning: urllib3 (2.6.3) or chardet (7.2.0)/charset_normalizer (3.4.6) 
   doesn't match a supported version!
   ```
   - **影響**: 機能的には問題なし（警告のみ）
   - **対応**: 依存関係の更新を検討

2. **SSL証明書検証エラー（一部サイト）**
   ```
   Title fetch failed for https://www.hosp.u-toyama.ac.jp/...: 
   certificate verify failed: unable to get local issuer certificate
   ```
   - **影響**: 一部の参考文献URLのタイトル取得に失敗
   - **対応**: エラーハンドリング済み（処理は継続）

---

### 4.3 未実装の改善計画

#### 📋 Phase 2 & 3: UI構造の抜本的整理（未実装）

詳細は `docs/ui_refactoring_plan.md` に記録済み。

**Phase 2: モード切り替えUIの統一**（3-4時間）
- 全自動モードとステップモードをラジオボタンで切り替え
- UI の重複を解消
- 難易度: ⭐⭐⭐☆☆

**Phase 3: Manual タブの統合と重複解消**（10-13時間）
- Manual タブを削除し、動画生成タブに統合
- Generator タブ内の「こだわりステップモード」アコーディオンを削除
- 難易度: ⭐⭐⭐⭐☆（高リスク）

---

### 4.4 TODOコメント・実装途中の箇所

現時点で特に重要なTODOはありません。Phase 2 & 3の実装が必要になった際は、`docs/ui_refactoring_plan.md` を参照してください。

---

### 4.5 技術的な課題

1. **非同期処理の一貫性**
   - Gradioのイベントハンドラーは同期関数だが、LLMクライアントは非同期
   - `asyncio.run()` で対応しているが、将来的にはGradio 5.x系の非同期対応を検討

2. **モデル名とAPI名のマッピング**
   - `costs.yaml` の `api_model` フィールドで実際のAPI呼び出し名を管理
   - 例: `gemini-3.1-pro` → `gemini-3.1-pro-preview`

3. **後方互換性**
   - 旧JSON形式（`speaker_id: "main"/"sub"`）を新形式（`speaker: "A"/"B"`）に自動変換
   - `DialogueTurn.upgrade_legacy_data()` で対応

---

## 5. Architecture Overview

### 5.1 システムアーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                    Gradio WebUI (app.py)                │
│  - 動画生成タブ（全自動/ステップモード）                │
│  - 手動制作タブ（Step A/B/C）                           │
│  - ダッシュボード（実行履歴/コスト分析）                │
│  - 設定タブ（API設定/YouTube設定）                      │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  Business Logic Layer                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Research     │  │ Script Gen   │  │ Cost Calc    │  │
│  │ Service      │  │ Service      │  │ Service      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Audio        │  │ Video        │  │ Publishing   │  │
│  │ Service      │  │ Service      │  │ Service      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                   External APIs / Tools                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Perplexity   │  │ Gemini/      │  │ VOICEVOX     │  │
│  │ API          │  │ OpenAI/      │  │ Engine       │  │
│  │              │  │ Anthropic    │  │              │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │ FFmpeg       │  │ YouTube      │                    │
│  │              │  │ Data API     │                    │
│  └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

### 5.2 データフロー（全自動モード）

```
1. ユーザー入力（テーマ、リサーチモード）
   ↓
2. Perplexity API → リサーチ結果取得
   ↓
3. Gemini/OpenAI/Anthropic → 台本生成
   ↓
4. VOICEVOX → 音声合成
   ↓
5. FFmpeg → 動画レンダリング（背景+音声+BGM+字幕）
   ↓
6. (オプション) YouTube Data API → 自動アップロード
   ↓
7. 完成動画 + メタデータ
```

---

## 6. Key Design Patterns

### 6.1 Clean Architecture

- **Core Layer**: インターフェース定義（`IScriptGenerator`, `IResearcher`）
- **Service Layer**: ビジネスロジック実装
- **UI Layer**: Gradio WebUI（プレゼンテーション層）

### 6.2 Factory Pattern

- `llm_factory.py`: プロバイダー名からLLMクライアントを動的生成
- 新しいLLMプロバイダーの追加が容易

### 6.3 Strategy Pattern

- リサーチモード（debate, voices, trivia, weekly_digest, lecture）
- 各モードで異なるシステムプロンプトを使用

### 6.4 Config-Driven Design

- `config.yaml`: アプリケーション設定
- `costs.yaml`: API料金設定（動的コスト計算）
- コード変更なしで設定変更可能

---

## 7. Testing Strategy

### 7.1 Mock Mode

- `dev.mock_mode: true` で API課金なしでテスト可能
- `tests/mock_data/` に固定データを配置

### 7.2 Unit Tests

- `pytest` を使用
- `tests/test_*.py` に単体テスト

---

## 8. Next Steps (Recommendations)

### 8.1 短期（1-2週間）

1. **urllib3 バージョン警告の解消**
   - 依存関係の更新

2. **Phase 2 UI改善の実装**
   - モード切り替えUIの統一（3-4時間）

### 8.2 中期（1-2ヶ月）

1. **Phase 3 UI改善の実装**
   - Manual タブの統合と重複解消（10-13時間）

2. **非同期処理の最適化**
   - Gradio 5.x系への移行検討

### 8.3 長期（3-6ヶ月）

1. **マルチモーダル対応**
   - 画像生成AI（DALL-E, Stable Diffusion）の統合

2. **リアルタイムプレビュー**
   - 台本生成中のストリーミング表示

---

**レポート作成者**: Cascade (AI Coding Assistant)  
**対象読者**: 設計・要件定義担当AI（Gemini/ChatGPT等）  
**目的**: プロジェクトの全容を正確に共有し、設計判断の材料を提供
