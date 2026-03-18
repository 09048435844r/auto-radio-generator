# 複数LLMプロバイダー使い分けガイド

> **Auto Radio Generator v3.4.0**  
> **作成日**: 2026-03-17  
> **対象**: Gemini / OpenAI / Anthropic

---

## 📋 概要

Auto Radio Generator v3.4.0では、台本生成に3つのLLMプロバイダーを選択できます。
それぞれの特徴を理解し、用途に応じて使い分けることで、最適な台本生成が可能になります。

---

## 🤖 プロバイダー比較

### Gemini（デフォルト）

**モデル**: `gemini-3.1-pro-preview` / `gemini-2.5-pro`

**特徴**:
- ✅ 日本語の自然な会話生成に優れる
- ✅ 長文の台本生成に強い（8192トークン）
- ✅ コスト効率が良い
- ✅ レスポンスが高速

**推奨用途**:
- 通常のラジオ台本生成
- 雑談・トリビア系コンテンツ
- 長時間の番組（50フレーズ以上）

**設定例**:
```yaml
script_generator:
  default_provider: "gemini"
  gemini:
    model: "gemini-3.1-pro-preview"
    max_tokens: 8192
```

---

### OpenAI

**モデル**: `gpt-4o-mini` / `gpt-4o`

**特徴**:
- ✅ Structured Outputsによる確実なJSON出力
- ✅ 論理的な構成に優れる
- ✅ 英語混じりのコンテンツに強い
- ⚠️ コストがやや高め（gpt-4o）

**推奨用途**:
- 論理的な解説・講座系コンテンツ
- ディベート形式の番組
- 技術解説・ビジネス系トピック

**設定例**:
```yaml
script_generator:
  default_provider: "openai"
  openai:
    model: "gpt-4o-mini"  # コスト重視
    # model: "gpt-4o"     # 品質重視
    max_tokens: 8192
    temperature: 0.85
```

---

### Anthropic

**モデル**: `claude-sonnet-4-6`

**特徴**:
- ✅ Tool Callingによる構造化出力
- ✅ 倫理的・バランスの取れた内容
- ✅ 長文コンテキストの理解に優れる
- ⚠️ コストが最も高い

**推奨用途**:
- 倫理的配慮が必要なトピック
- 複雑な議論・多角的な視点が必要な番組
- 高品質な台本が必要な場合

**設定例**:
```yaml
script_generator:
  default_provider: "anthropic"
  anthropic:
    model: "claude-sonnet-4-6"
    max_tokens: 8192
    temperature: 0.85
```

---

## 🔧 セットアップ

### 1. APIキーの取得

#### Gemini API
1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. 「Get API Key」をクリック
3. APIキーをコピー

#### OpenAI API
1. [OpenAI Platform](https://platform.openai.com/) にアクセス
2. 「API Keys」から新しいキーを作成
3. APIキーをコピー

#### Anthropic API
1. [Anthropic Console](https://console.anthropic.com/) にアクセス
2. 「API Keys」から新しいキーを作成
3. APIキーをコピー

### 2. 環境変数の設定

`.env`ファイルに以下を追加：

```env
# Gemini API Key（必須）
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# OpenAI API Key（オプション）
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Anthropic API Key（オプション）
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. プロバイダーの選択

#### 方法1: Gradio UIで選択（推奨）

1. `python app.py` でUIを起動
2. 「Generator」タブの「LLMプロバイダー」ドロップダウンから選択
3. 「動画を生成する」をクリック

#### 方法2: config.yamlでデフォルト設定

```yaml
script_generator:
  default_provider: "gemini"  # "gemini" | "openai" | "anthropic"
```

---

## 💡 使い分けのヒント

### コスト重視
1. **Gemini** (最もコスト効率が良い)
2. **OpenAI gpt-4o-mini** (バランス型)
3. **Anthropic** (最も高コスト)

### 品質重視
1. **Anthropic Claude 3.5 Sonnet** (最高品質)
2. **OpenAI gpt-4o** (高品質)
3. **Gemini** (標準品質)

### 速度重視
1. **Gemini** (最速)
2. **OpenAI gpt-4o-mini** (高速)
3. **Anthropic** (やや遅い)

### 用途別推奨

| 用途 | 推奨プロバイダー | 理由 |
|------|-----------------|------|
| 雑談・トリビア | Gemini | 自然な会話、コスト効率 |
| ディベート | OpenAI | 論理的構成 |
| 解説・講座 | OpenAI | 構造化された説明 |
| ニュース解説 | Gemini | バランスの良い内容 |
| 倫理的トピック | Anthropic | 配慮された内容 |
| 技術解説 | OpenAI | 正確な情報整理 |

---

## 🔍 トラブルシューティング

### エラー: "API Key not found"

**原因**: APIキーが設定されていない

**解決策**:
1. `.env`ファイルに該当するAPIキーを追加
2. アプリケーションを再起動

### エラー: "401 Unauthorized"

**原因**: APIキーが無効または期限切れ

**解決策**:
1. APIキーが正しいか確認
2. プロバイダーのコンソールで新しいキーを発行

### エラー: "429 Rate Limit"

**原因**: API呼び出し制限に達した

**解決策**:
1. しばらく待ってから再試行
2. 別のプロバイダーに切り替え
3. プロバイダーのプランをアップグレード

### 出力が途中で切れる

**原因**: `max_tokens`制限に達した

**解決策**:
1. `config.yaml`の`max_tokens`を増やす（最大16384）
2. テーマを簡潔にする
3. 別のプロバイダーを試す

---

## 📊 コスト比較（目安）

### 台本生成1回あたりのコスト（8192トークン出力想定）

| プロバイダー | モデル | 入力コスト | 出力コスト | 合計 |
|-------------|--------|-----------|-----------|------|
| Gemini | gemini-3.1-pro-preview | $0.001 | $0.004 | **$0.005** |
| OpenAI | gpt-4o-mini | $0.002 | $0.008 | **$0.010** |
| OpenAI | gpt-4o | $0.025 | $0.100 | **$0.125** |
| Anthropic | claude-3-5-sonnet | $0.030 | $0.150 | **$0.180** |

※ 2026年3月時点の料金。最新情報は各プロバイダーの公式サイトを参照してください。

---

## 🚀 ベストプラクティス

### 1. デフォルトはGeminiを推奨
- コスト効率と品質のバランスが最適
- 日本語コンテンツに最適化

### 2. 用途に応じて切り替え
- 論理的な内容: OpenAI
- 倫理的配慮: Anthropic
- 通常の雑談: Gemini

### 3. APIキーは全て設定
- 障害時のフォールバック用
- 用途に応じた柔軟な切り替え

### 4. コスト管理
- Dashboardタブでコスト推移を確認
- 高コストプロバイダーは必要時のみ使用

---

## 📚 関連ドキュメント

- [README.md](../README.md) - プロジェクト全体の概要
- [ROADMAP.md](../ROADMAP.md) - 開発ロードマップ
- [config.yaml](../config.yaml) - 設定ファイル
- [.env.example](../.env.example) - 環境変数テンプレート

---

**Auto Radio Generator v3.4.0** | "Input Minimal, Data Maximal"
