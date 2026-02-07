# 🎙️ 自動ラジオ動画生成システム v3.1.2

AIが台本を作成し、音声合成・BGM合成を行い、YouTube/Podcast用のラジオ動画（MP4）を自動生成するシステムです。

## 📋 機能

### コア機能
- **リサーチ**: Perplexity API でテーマを事前調査（5モード対応）
- **台本生成**: Gemini API で多様な形式の台本を自動生成
- **音声合成**: VOICEVOX で2人のパーソナリティの音声を合成
- **字幕生成**: ASS形式の字幕ファイルを自動生成（ワイドスクリーン最適化）
- **動画生成**: FFmpeg で背景画像・音声・BGM・字幕を合成
- **サムネイル生成**: センターセーフ方式で1:1トリミング対応
- **YouTubeチャプター**: 自動生成されたセクションマーカーでチャプター対応

### v3.1.2 新機能（GPU / Mock / UI強化）
- 🚀 **NVENC GPU高速化**: NVIDIA GPUによるハードウェアエンコード対応（h264_nvenc）
  - `config.yaml` の `video_renderer.use_gpu` で切り替え可能
  - GPU非搭載環境では自動的にCPU（libx264）にフォールバック
- 🧪 **Mock開発モード**: API課金なしでワークフロー全体をテスト可能
  - `config.yaml` の `dev.mock_mode` で有効化
  - ローカルの固定データ（`tests/mock_data/`）を使用して高速に動作確認
- 📊 **進捗可視化UI**: Gradio進捗バーで各フェーズの状況をリアルタイム表示
  - 🤔 企画 → 🔍 リサーチ → 📝 台本 → 🗣️ 音声 → 🎬 動画 → ✨ 完了
- 🛡️ **後方互換性強化**: 旧JSON形式（`speaker_id`/`dialogue`）の自動変換バリデータ追加

### v3.1.1 新機能（JSON Mode Patch）
- 🔧 **Native JSON Mode**: Gemini APIのJSONモードを有効化し、解析の完全安定化を実現
  - `response_mime_type="application/json"`でAPIレベルのJSON保証
  - マークダウンブロック抽出や正規表現による回避ロジックを削除
  - 約30行のエラーハンドリングコードを簡素化
  - APIの機能を活かしたスマートな実装に移行

### v3.1 新機能（Phase 2）
- 🏷 **Automated Metadata**: タイトル・概要・サムネイル文字の完全自動生成（チャプター付き）
  - AI生成タイトルに制作日を自動付与
  - 概要欄の冒頭にチャプターリストを配置
  - サムネイル中央にAI生成キャッチフレーズ、右上に日付バッジ
- 📜 **High-Density Script**: 50フレーズ以上の深掘り台本生成ロジック
  - リスナーメールセクションの充実化
  - セクション間の自然な接続強化
- 🎨 **Modern UI**: カード型レイアウトによる直感的な操作画面
  - タブ式インターフェースで自動生成とマニュアル制作を分離
  - 設定の永続化とワンクリック復元
- 🛡️ **Stability**: 静的解析に基づく堅牢なエラー対策
  - JSON解析の改善（マークダウンブロック対応）
  - テーマ引き継ぎロジックの修正

### v3.0 新機能（Phase 1）
- **タブ式UI**: 自動生成とマニュアル制作を分離した直感的なインターフェース
- **マニュアル制作ワークフロー**: 3ステップで完結する柔軟な制作フロー
  - **Step A: 台本生成** - リサーチ結果から台本を生成
  - **Step B: 音声合成** - 台本を編集して音声を合成
  - **Step C: 動画レンダリング** - 背景画像とBGMを追加して動画を生成
- **設定の永続化**: ユーザー設定を自動保存・復元
- **処理ログ出力**: 各実行の詳細ログをファイルに保存
- **自動データ連携**: Step A→B→Cで生成物が自動的に次のステップに反映

### v2.1 機能
- **週次ニュースダイジェスト**: 直近1週間の重要ニュースをトップ3選定
- **Markdownレポート**: リサーチ結果を構造化された読みやすい形式で保存
- **センターセーフサムネイル**: Podcast配信時の正方形トリミングに対応
- **限界設定字幕**: 画面端ギリギリまで拡大した超大型字幕（モバイル最適化）

### v2.0 機能
- **Web UI**: Gradio ベースのブラウザ操作画面
- **リサーチモード**: ディベート / 世間の声 / トリビア / 週次ダイジェスト / 解説・講座
- **多様な台本形式**: 
  - 3部構成（本題/リスナーメール/エンディング）
  - ニュースダイジェスト（トップ3形式）
  - 講座形式（先生と生徒の対話）
- **音声スペクトラム**: 画面下部に音声波形を表示

## 🚀 セットアップ

### 必要な外部ツール

| ツール | バージョン | 備考 |
|--------|-----------|------|
| **Python** | 3.10+ | 必須 |
| **FFmpeg** | 6.0+ | NVENC対応ビルド推奨（GPU高速化に必要） |
| **VOICEVOX Engine** | 0.24+ | GPU版推奨（音声合成の高速化） |

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
| `researcher.model` | リサーチ用モデル (デフォルト: sonar-reasoning-pro) |
| `researcher.modes` | リサーチモード定義 (debate/voices/trivia/weekly_digest/lecture) |
| `script_generator.gemini.model` | 台本生成用モデル |
| `script_generator.structure` | 台本構成比率 (本題/メール/エンディング) |
| `audio_synthesizer.speakers.main` | メインパーソナリティのVOICEVOX話者ID |
| `audio_synthesizer.speakers.sub` | サブパーソナリティのVOICEVOX話者ID |
| `audio_synthesizer.speed_scale` | 話速 (1.0=標準、1.1=やや速め) |
| `video_renderer.bgm_volume` | BGM音量 (0.0〜1.0) |
| `video_renderer.enable_spectrum` | 音声スペクトラム表示 |
| `personalities` | 各パーソナリティの名前・性格設定 |

### リサーチモード

| モード | 説明 | 用途 |
|--------|------|------|
| ディベート | 賛成・反対の両論を調査 | 議論形式の番組 |
| 世間の声 | SNSの反応や一般意見を収集 | カジュアルな雑談番組 |
| トリビア | あまり知られていない事実を調査 | 雑学・豆知識番組 |
| 今週のまとめ | 直近1週間のニュースをトップ3選定 | ニュースダイジェスト |
| 解説・講座 | 初心者向けに比喩を使って解説 | 教育・学習番組 |

### VOICEVOX話者ID例

| ID | キャラクター |
|----|-------------|
| 1 | 四国めたん（ノーマル） |
| 2 | 四国めたん（あまあま） |
| 3 | ずんだもん（ノーマル） |
| 8 | 春日部つむぎ |

## 📁 出力ファイル

### 自動生成モード
生成されたファイルは `output/YYYYMMDD_HHMMSS/` に保存されます：

```
output/
└── 20241221_143000/
    ├── audio/
    │   ├── combined_audio.wav   # 合成音声
    │   └── subtitles.ass        # 字幕ファイル（ASS形式）
    ├── videos/
    │   └── radio_20241221_143000.mp4  # 完成動画
    ├── research.json            # リサーチ結果（JSON形式）
    ├── research_report.md       # リサーチレポート（Markdown形式）
    ├── script.json              # 生成された台本
    ├── metadata.txt             # YouTube投稿用メタデータ
    ├── thumbnail.png            # サムネイル画像（1280x720、センターセーフ対応）
    └── processing_log.txt       # 処理ログ
```

### マニュアル制作モード
マニュアル制作の出力は `output/manual_builds/YYYYMMDD_HHMMSS/` に保存されます：

```
output/
└── manual_builds/
    └── 20241221_143000/
        ├── combined_audio.wav   # Step B: 合成音声
        ├── subtitles.ass        # Step B: 字幕ファイル
        └── video.mp4            # Step C: 完成動画
```

## 🏗️ アーキテクチャ

```
auto_radio_generator/
├── app.py                   # Web UI エントリーポイント
├── main.py                  # CLI エントリーポイント
├── workflow.py              # 共通ワークフロー
├── config.yaml              # 設定ファイル
├── requirements.txt         # Python依存パッケージ
├── user_settings.json       # ユーザー設定（自動生成）
├── core/                    # ドメイン層
│   ├── interfaces/          # 抽象インターフェース (ABC)
│   │   ├── researcher.py    # リサーチャーIF
│   │   ├── script_generator.py
│   │   ├── audio_synthesizer.py
│   │   └── video_renderer.py
│   ├── models/              # Pydanticモデル
│   │   ├── config.py        # 設定モデル
│   │   ├── script.py        # 台本モデル
│   │   └── usage.py         # 使用量モデル
│   └── settings_manager.py  # 設定永続化
├── services/                # アプリケーション層
│   ├── research/            # リサーチ (Perplexity)
│   ├── script_generation/   # 台本生成 (Gemini)
│   ├── audio_synthesis/     # 音声合成 (VOICEVOX)
│   ├── video_rendering/     # 動画生成 (FFmpeg)
│   ├── media_processing/    # メディア処理
│   │   └── thumbnail_generator.py  # サムネイル生成
│   └── cost_calculator.py   # コスト計算
├── assets/                  # 静的リソース
│   ├── backgrounds/         # 背景画像 (10枚以上)
│   └── bgm/                 # BGM音楽 (8曲以上)
└── output/                  # 生成物
    ├── YYYYMMDD_HHMMSS/     # 自動生成モード
    └── manual_builds/       # マニュアル制作モード
```

## 🔧 拡張

インターフェース（ABC）を使用しているため、以下の拡張が容易です：

- **OpenAI対応**: `IScriptGenerator` を継承して実装
- **ElevenLabs対応**: `IAudioSynthesizer` を継承して実装
- **別レンダラー対応**: `IVideoRenderer` を継承して実装

## 📝 ライセンス

MIT License
