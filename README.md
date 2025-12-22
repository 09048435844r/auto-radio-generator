# 🎙️ 自動ラジオ動画生成システム v2.0

AIが台本を作成し、音声合成・BGM合成を行い、YouTube用のラジオ動画（MP4）を自動生成するシステムです。

## 📋 機能

### コア機能
- **リサーチ**: Perplexity API でテーマを事前調査（3モード対応）
- **台本生成**: Gemini API で3部構成の台本を自動生成
- **音声合成**: VOICEVOX で2人のパーソナリティの音声を合成
- **字幕生成**: SRT形式の字幕ファイルを自動生成
- **動画生成**: FFmpeg で背景画像・音声・BGM・字幕を合成

### v2.0 新機能
- **Web UI**: Gradio ベースのブラウザ操作画面
- **リサーチモード**: ディベート / 世間の声 / トリビア
- **3部構成台本**: 本題(70%) / リスナーメール(20%) / エンディング(10%)
- **音声スペクトラム**: 画面下部に音声波形を表示

## 🚀 セットアップ

### 1. 依存パッケージのインストール

```bash
cd auto_radio_generator
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env.example` を `.env` にコピーし、APIキーを設定：

```bash
copy .env.example .env
```

```env
PERPLEXITY_API_KEY=pplx-xxxxxxxx  # Perplexity使用時
GEMINI_API_KEY=AIzaSyxxxxxxxx     # Gemini使用時（推奨）
VOICEVOX_BASE_URL=http://localhost:50021
```

### 3. アセットの配置

以下のファイルを配置してください：

- `assets/backgrounds/default.png` - 背景画像 (1920x1080推奨)
- `assets/bgm/default.mp3` - BGM音楽ファイル

### 4. VOICEVOXエンジンの起動

```bash
# VOICEVOXエンジンを起動
..\voicevox_engine-windows-nvidia-0.24.0\windows-nvidia\run.exe
```

### 5. 実行

**Web UI（推奨）**
```bash
python app.py
```
ブラウザで http://127.0.0.1:7861 を開きます。

**CLI版**
```bash
python main.py
```

## ⚙️ 設定

`config.yaml` で以下の設定が可能：

| 設定項目 | 説明 |
|---------|------|
| `researcher.model` | リサーチ用モデル (デフォルト: sonar-pro) |
| `researcher.modes` | リサーチモード定義 (debate/voices/trivia) |
| `script_generator.gemini.model` | 台本生成用モデル |
| `script_generator.structure` | 台本構成比率 (本題/メール/エンディング) |
| `audio_synthesizer.speakers.main` | メインパーソナリティのVOICEVOX話者ID |
| `audio_synthesizer.speakers.sub` | サブパーソナリティのVOICEVOX話者ID |
| `video_renderer.bgm_volume` | BGM音量 (0.0〜1.0) |
| `video_renderer.enable_spectrum` | 音声スペクトラム表示 |
| `personalities` | 各パーソナリティの名前・性格設定 |

### VOICEVOX話者ID例

| ID | キャラクター |
|----|-------------|
| 1 | 四国めたん（ノーマル） |
| 3 | ずんだもん（ノーマル） |
| 8 | 春日部つむぎ |

## 📁 出力ファイル

生成されたファイルは `output/YYYYMMDD_HHMMSS/` に保存されます：

```
output/
└── 20241221_143000/
    ├── audio/
    │   └── combined_audio.wav   # 合成音声
    ├── videos/
    │   └── radio_20241221_143000.mp4  # 完成動画
    ├── subtitles.srt            # 字幕ファイル
    └── script.json              # 生成された台本
```

## 🏗️ アーキテクチャ

```
auto_radio_generator/
├── app.py                   # Web UI エントリーポイント
├── main.py                  # CLI エントリーポイント
├── workflow.py              # 共通ワークフロー
├── config.yaml              # 設定ファイル
├── core/                    # ドメイン層
│   ├── interfaces/          # 抽象インターフェース (ABC)
│   │   ├── researcher.py    # リサーチャーIF
│   │   ├── script_generator.py
│   │   ├── audio_synthesizer.py
│   │   └── video_renderer.py
│   └── models/              # Pydanticモデル
├── services/                # アプリケーション層
│   ├── research/            # リサーチ (Perplexity)
│   ├── script_generation/   # 台本生成 (Gemini)
│   ├── audio_synthesis/     # 音声合成 (VOICEVOX)
│   └── video_rendering/     # 動画生成 (FFmpeg)
├── assets/                  # 静的リソース
└── output/                  # 生成物
```

## 🔧 拡張

インターフェース（ABC）を使用しているため、以下の拡張が容易です：

- **OpenAI対応**: `IScriptGenerator` を継承して実装
- **ElevenLabs対応**: `IAudioSynthesizer` を継承して実装
- **別レンダラー対応**: `IVideoRenderer` を継承して実装

## 📝 ライセンス

MIT License
