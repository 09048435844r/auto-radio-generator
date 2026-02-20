# 🎙️ 自動ラジオ動画生成システム v3.3.0

Perplexity + Gemini + VOICEVOX + FFmpeg を連携し、
リサーチから台本生成、音声合成、動画レンダリング、YouTube投稿用メタデータ作成までを一気通貫で自動化するプロジェクトです。

## 📋 Project Overview

- **目的**: YouTube/Podcast向けラジオ動画（MP4）の制作工数を削減し、品質を安定化する
- **入出力**: テーマ入力から `script.json` / `metadata.txt` / `thumbnail.png` / `video.mp4` を生成
- **実行形態**: Gradio Web UI (`app.py`) と CLI (`main.py`) の両対応
- **ワークフロー中心**: `workflow.py` が各サービスを統合して処理順序を管理

## 📋 Current Features

### コア機能
- **リサーチ**: Perplexity API でテーマを事前調査（5モード対応）
- **台本生成**: Gemini API で多様な形式の台本を自動生成
- **音声合成**: VOICEVOX で2人のパーソナリティの音声を合成
- **字幕生成**: ASS形式の字幕ファイルを自動生成（ワイドスクリーン最適化）
- **動画生成**: FFmpeg で背景画像・音声・BGM・字幕を合成
- **サムネイル生成**: センターセーフ方式で1:1トリミング対応
- **YouTubeチャプター**: 自動生成されたセクションマーカーでチャプター対応
- **概要欄の堅牢化**:
  - YouTube向けサニタイズ（制御文字除去、Unicode正規化、5000文字制限）
  - 参考文献の3行構造（📄タイトル / 🔗URL / 空行）
  - セクション間余白ルール（見出し前2行、見出し後0〜1行）
  - エンコーディング耐性のあるWebタイトル取得（`chardet`）

### v3.3.0 新機能（Negative Prompt / Audio Pro / Quality）
- 🧭 **Manually Controlled Topics**: 「避けてほしい話題」(Negative Prompt) による生成内容の制御
  - UI上で除外トピックを自由入力し、Geminiプロンプトに自動反映
  - スペースやカンマ区切りで複数トピック指定可能
- 🔊 **Pro-Level Audio**: ラウドネスノーマライゼーション (-14 LUFS) による音圧自動調整
  - YouTube推奨基準 (I=-14, TP=-1, LRA=11) に準拠
  - FFmpeg `loudnorm` フィルタで音声ミキシング後に自動適用
- 📊 **Visual Progress**: 詳細な進捗バー表示
  - Gradio進捗バーで各フェーズの状況をリアルタイム表示
  - 🤔 企画 → 🔍 リサーチ → 📝 台本 → 🗣️ 音声 → 🎬 動画 → ✨ 完了
- 🚀 **High Performance**: Mockモード開発とNVENC (GPU) レンダリング
  - NVIDIA GPUによるハードウェアエンコード対応（h264_nvenc）
  - API課金なしでワークフロー全体をテスト可能なMockモード

### v3.1.2 以前の機能（GPU / Mock / UI強化）
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

### システム要件 (Requirements)

| ツール | バージョン | 備考 |
|--------|-----------|------|
| **Python** | 3.10+ | 必須 |
| **FFmpeg** | 6.0+ | NVENC対応ビルド推奨（GPU高速化に必要） |
| **VOICEVOX Engine** | 0.24+ | GPU版推奨（音声合成の高速化） |

Pythonパッケージは `requirements.txt` で管理しています（主な依存: `google-genai`, `openai`, `gradio`, `requests`, `beautifulsoup4`, `chardet`, `pytest`）。

> **Pythonバージョン運用方針（メンテナンス注記）**  
> 現在は **Python 3.10.6** で安定動作しており、**2026年10月（サポート期限）までは現行環境を維持**します。開発効率を優先しつつ、
> Google API ライブラリ（`google-api-core` 系）の Python 3.10 サポート終了（**2026-10-04**）に伴い、
> 将来的には **Python 3.11 以上** への移行が必要です。

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

## 🔑 YouTube API のセットアップ

YouTube への自動アップロード機能を使う場合、プロジェクトルートに `client_secret.json` が必要です。

### 必要ファイル

- `client_secret.json`（OAuth クライアント情報）
- `client_secret.json.example`（ダミー構成テンプレート、詳細はこのファイルを参照）

### 取得方法（Google Cloud Console）

1. Google Cloud Console でプロジェクトを作成
2. **YouTube Data API v3** を有効化
3. 「認証情報」から **OAuth クライアント ID** を作成（アプリケーション種別: **デスクトップアプリ**）
4. ダウンロードした JSON をプロジェクトルートに `client_secret.json` として配置

### セキュリティ上の注意（重要）

- `client_secret.json` と `token.json` は **絶対にリポジトリへコミットしないでください**。
- 本リポジトリでは `.gitignore` で除外設定済みです。
- 構成の参考が必要な場合は `client_secret.json.example` を使用してください（ダミー値のみ）。

## 🧪 開発・テスト (Development & Testing)

### 手動テスト

プロジェクトルートで以下を実行すると、単体テストを手動実行できます。

```bash
pytest
```

### 自動チェック（pre-commit hook）

`git commit` 実行時に `.git/hooks/pre-commit` が自動で `pytest` を実行します。

- テスト失敗時: `🚫 Tests Failed! Commit rejected.` を表示し、コミットを中止
- テスト成功時: `✅ Tests Passed!` を表示し、コミットを許可

### フック再生成手順（clone直後）

`.git/hooks/` は通常リポジトリ管理対象外のため、clone 直後は pre-commit hook を再配置してください。

```bash
# プロジェクトルートで実行
copy hooks\pre-commit .git\hooks\pre-commit
```

Git Bash を使う場合:

```bash
cp hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

※ `hooks/pre-commit` はリポジトリ管理されるフック実体です。clone 後に `.git/hooks/pre-commit` へコピーして利用してください。

### 現在のテスト範囲

現時点では、`services/video_rendering/ffmpeg_renderer.py` の Windows パス変換ロジック（例: 字幕パスのエスケープ処理）を中心に単体テストを整備しています。

主な対象:
- `_escape_windows_path()` のパス変換（`\\` → `/`, `:` → `\\:`）
- スペース・日本語・UNC パスなどのエッジケース

## 🔭 今後の展望 (Future Outlook)

- **視聴者エンゲージメントの自動化**: 動画公開と同時に、参考文献や台本要約などの補足情報をコメント欄へ自動提供し、視聴者の利便性と信頼性を向上させる。
- **メタデータの高度化**: タイムスタンプとリッチな概要欄により、視聴者の利便性を最大化し、YouTube 検索におけるプレゼンスを強化する。
- **情報の透明性**: 参考文献の自動掲載により、AI 生成コンテンツとしての信頼性と価値を高める。
- **設計ヒント**: `YouTubeClient` に `insert_comment(video_id, text)` のようなメソッドを追加し、`workflow.py` の最終工程で呼び出す構成を想定。
- **実装ヒント（チャプター概要欄）**: `workflow.py` の動画生成フェーズで各パートの累積時間を計算し、チャプター付き説明文を `YouTubeClient.upload_video(..., description=...)` に渡す構成を想定。

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
│   ├── video_rendering/     # 動画生成 (FFmpeg)・字幕生成
│   ├── publishing/          # YouTube投稿メタデータ生成・アップロード
│   ├── media_processing/    # メディア処理
│   │   └── thumbnail_generator.py  # サムネイル生成
│   ├── cost_calculator.py   # APIコスト計算
│   └── ...                  # 補助ユーティリティ
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
