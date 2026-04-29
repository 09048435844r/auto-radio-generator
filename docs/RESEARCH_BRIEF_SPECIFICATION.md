# リサーチデータJSON仕様書 (ResearchBrief)

**Version:** 3.5.0  
**Last Updated:** 2026-04-12  
**Purpose:** 外部AI・手動作成によるリサーチデータの構造定義

---

## 概要

`ResearchBrief`は、リサーチフェーズの出力成果物であり、台本作成フェーズへの入力として使用されます。
このJSONファイルを外部AIや手動で作成することで、リサーチフェーズをスキップして直接台本生成を実行できます。

---

## ファイル形式

- **ファイル名:** `research_brief.json` (任意の名前でも可)
- **文字エンコーディング:** UTF-8
- **フォーマット:** JSON (整形推奨、`indent=2`)

---

## JSON構造定義

### ルートオブジェクト

| フィールド名 | 型 | 必須 | 説明 |
|------------|-----|------|------|
| `session_id` | string | ✅ | セッションID (例: `20260404_065500`) |
| `theme` | string | ✅ | リサーチテーマ (例: `持続血糖測定器CGMについて`) |
| `research_mode` | string | ✅ | リサーチモード (`debate` / `voices` / `trivia` / `lecture` / `weekly_digest`) |
| `created_at` | string | ✅ | 作成日時 (ISO 8601形式: `2026-04-04T06:55:00.123456`) |
| `research_content` | string | ✅ | 収集したリサーチ内容の全文 (詳細は後述) |
| `research_sources` | array | ✅ | 参考文献リスト (詳細は後述) |
| `queries` | array | ✅ | 実行した検索クエリのリスト |
| `angle` | string | ✅ | 台本の切り口・コンセプト |
| `curated_topics` | array / null | ❌ | キュレーション済みトピック (オーケストレーター使用時のみ) |
| `perplexity_usage` | object / null | ❌ | Perplexity API使用量 |
| `gemini_usage_planning` | object / null | ❌ | Gemini API使用量 (プランニングフェーズ) |

---

### 1. `session_id` (string, 必須)

**説明:** セッションを一意に識別するID。通常は`YYYYmmdd_HHMMSS`形式のタイムスタンプ。

**例:**
```json
"session_id": "20260404_065500"
```

**生成ルール:**
- 形式: `YYYYmmdd_HHMMSS` (例: `20260404_065500`)
- 任意の一意な文字列でも可 (例: `custom_research_001`)

---

### 2. `theme` (string, 必須)

**説明:** リサーチのテーマ。台本生成時のメインテーマとして使用されます。

**例:**
```json
"theme": "持続血糖測定器CGM FreeStyleリブレについて"
```

**推奨事項:**
- 具体的で明確なテーマを設定
- 30-100文字程度
- 専門用語を含めても可

---

### 3. `research_mode` (string, 必須)

**説明:** リサーチモード。台本の構成スタイルを決定します。

**有効な値:**
| 値 | 説明 |
|----|------|
| `lecture` | 講義形式（基礎から応用まで体系的に解説） |
| `debate` | 討論形式（賛否両論・多角的視点） |
| `voices` | 体験談形式（実例・ケーススタディ中心） |
| `trivia` | トリビア形式（意外な事実・雑学） |
| `weekly_digest` | 週刊ダイジェスト形式（最新ニュース・トレンド） |

**例:**
```json
"research_mode": "lecture"
```

---

### 4. `created_at` (string, 必須)

**説明:** リサーチデータの作成日時。ISO 8601形式。

**例:**
```json
"created_at": "2026-04-04T06:55:00.123456"
```

**生成方法 (Python):**
```python
from datetime import datetime
created_at = datetime.now().isoformat()
```

---

### 5. `research_content` (string, 必須)

**説明:** 収集したリサーチ内容の全文。台本生成AIがこのテキストを元に対話を構成します。

**重要:** このフィールドが台本の品質を決定します。

#### 推奨構造

```
## 1. [トピック1のタイトル]

[詳細な説明文。専門用語の定義、具体例、数値データ、比喩表現などを含む]

### 1.1 [サブトピック]

[さらに詳細な説明]

## 2. [トピック2のタイトル]

[詳細な説明文]

...
```

#### 内容要件

1. **文字数:** 5,000文字以上推奨 (最低3,000文字)
2. **構造化:** Markdown形式で見出し (`##`, `###`) を使用
3. **具体性:** 抽象的な説明だけでなく、具体例・数値・比喩を含める
4. **多角性:** 複数の視点・側面を網羅
5. **引用:** 重要な情報には出典を明記 (例: `[1]`, `[2]`)

#### 良い例

```markdown
## 1. 持続血糖測定器（CGM）とは何か

持続血糖測定器（CGM: Continuous Glucose Monitoring）は、皮膚に装着した小型センサーで血糖値を継続的に監視するデバイスである[1]。従来の血糖測定方法では指先を針で刺して血液を採取する必要があるが、CGMは指先穿刺検査の必要性を大幅に減らし、患者が積極的に糖尿病を管理するのを助けている[2]。

### 1.1 一言で言うと何か（3つの異なる表現）

1. **「貼り付けるだけで血糖値を自動記録する健康管理デバイス」**: 従来の手動測定から自動化への転換
2. **「リアルタイム血糖監視システム」**: 常時データ取得による予防医療への対応
3. **「スマートフォン連携型の個人用血糖管理プラットフォーム」**: デジタルヘルスの実装例

### 1.2 身近なものへの比喩

#### 比喩1: スマートウォッチと同じ発想の進化系

CGMは、スマートウォッチが心拍数を常時監視するのと同じ原理で、血糖値を常時監視する。スマートウォッチは「腕に貼り付けて自動的に健康データを記録」し、スマートフォンと連携してアプリで確認できる。CGMも全く同じ流れで、背中や腕に貼り付けたセンサーが自動的に血糖データを記録し、スマートフォンアプリで確認できる[3]。

...
```

#### 悪い例

```
持続血糖測定器は血糖値を測る機械です。糖尿病の人が使います。便利です。
```
→ **問題点:** 具体性がない、文字数不足、構造化されていない

---

### 6. `research_sources` (array, 必須)

**説明:** 参考文献のリスト。YouTube概要欄の「参考文献」セクションに表示されます。

**配列要素の構造:**

| フィールド名 | 型 | 必須 | 説明 |
|------------|-----|------|------|
| `title` | string | ✅ | ソースのタイトル |
| `url` | string | ✅ | ソースのURL (有効なHTTP/HTTPS URL) |
| `snippet` | string / null | ❌ | 引用スニペット (オプション) |

**例:**
```json
"research_sources": [
  {
    "title": "FreeStyle Libreの仕組みと使い方 | 糖尿病専門医が解説",
    "url": "https://example.com/article/freestyle-libre",
    "snippet": null
  },
  {
    "title": "持続血糖測定器の比較研究 - 日本糖尿病学会",
    "url": "https://example.com/research/cgm-comparison",
    "snippet": "CGMは従来のSMBGと比較して、低血糖イベントの検出率が3倍高い"
  }
]
```

**推奨事項:**
- 最低5件、推奨10件以上
- 信頼性の高いソース (学術論文、公式サイト、専門家の記事)
- URLは有効なリンクであること
- `snippet`は省略可 (通常は`null`)

---

### 7. `queries` (array, 必須)

**説明:** リサーチ時に実行した検索クエリのリスト。

**例:**
```json
"queries": [
  "持続血糖測定器 CGM とは何か: 専門用語を使わない定義、身近なものへの比喩3つ以上、技術的な仕組み",
  "CGM 活用事例: 具体的な導入事例、臨床試験データ、成功事例5つ以上",
  "CGM よくある誤解と実態: 誤解の内容と医学的に正しい理解、専門家の注意点"
]
```

**推奨事項:**
- 3-5件のクエリ
- 各クエリは具体的で詳細な指示を含む
- `research_content`の構造と対応させる

---

### 8. `angle` (string, 必須)

**説明:** 台本の切り口・コンセプト。台本生成AIがこの方向性に沿って対話を構成します。

**例:**
```json
"angle": "初心者でも理解できる！CGMの仕組みを身近な比喩で徹底解説"
```

**推奨事項:**
- 50-150文字程度
- ターゲット層を明確に (例: 初心者向け、専門家向け)
- 独自の視点・切り口を示す (例: 「意外な事実」「最新研究」「実体験」)

---

### 9. `curated_topics` (array / null, オプション)

**説明:** オーケストレーター機能が生成したキュレーション済みトピック。通常は`null`で問題ありません。

**例:**
```json
"curated_topics": null
```

**高度な使用例 (オーケストレーター互換):**
```json
"curated_topics": [
  {
    "topic_id": "topic_1",
    "title": "CGMの基礎知識",
    "description": "CGMとは何か、仕組み、従来の測定方法との違い",
    "priority": 1
  }
]
```

---

### 10. `perplexity_usage` (object / null, オプション)

**説明:** Perplexity API使用量の記録。コスト計算に使用されます。

**例:**
```json
"perplexity_usage": {
  "request_count": 3
}
```

**省略可:** 外部作成の場合は`null`または省略

---

### 11. `gemini_usage_planning` (object / null, オプション)

**説明:** Gemini API使用量の記録 (プランニングフェーズ)。

**例:**
```json
"gemini_usage_planning": {
  "provider": "gemini",
  "model_name": "gemini-2.0-flash-exp",
  "input_tokens": 753,
  "output_tokens": 444,
  "request_count": 1
}
```

**省略可:** 外部作成の場合は`null`または省略

---

## 完全なサンプルJSON

```json
{
  "session_id": "20260404_065500",
  "theme": "持続血糖測定器CGM FreeStyleリブレについて",
  "research_mode": "lecture",
  "created_at": "2026-04-04T06:55:00.123456",
  "research_content": "## 1. 持続血糖測定器（CGM）とは何か\n\n持続血糖測定器（CGM: Continuous Glucose Monitoring）は、皮膚に装着した小型センサーで血糖値を継続的に監視するデバイスである[1]。従来の血糖測定方法では指先を針で刺して血液を採取する必要があるが、CGMは指先穿刺検査の必要性を大幅に減らし、患者が積極的に糖尿病を管理するのを助けている[2]。\n\n### 1.1 一言で言うと何か（3つの異なる表現）\n\n1. **「貼り付けるだけで血糖値を自動記録する健康管理デバイス」**: 従来の手動測定から自動化への転換\n2. **「リアルタイム血糖監視システム」**: 常時データ取得による予防医療への対応\n3. **「スマートフォン連携型の個人用血糖管理プラットフォーム」**: デジタルヘルスの実装例\n\n### 1.2 身近なものへの比喩\n\n#### 比喩1: スマートウォッチと同じ発想の進化系\n\nCGMは、スマートウォッチが心拍数を常時監視するのと同じ原理で、血糖値を常時監視する...",
  "research_sources": [
    {
      "title": "FreeStyle Libreの仕組みと使い方 | 糖尿病専門医が解説",
      "url": "https://example.com/article/freestyle-libre",
      "snippet": null
    },
    {
      "title": "持続血糖測定器の比較研究 - 日本糖尿病学会",
      "url": "https://example.com/research/cgm-comparison",
      "snippet": null
    }
  ],
  "queries": [
    "持続血糖測定器 CGM とは何か: 専門用語を使わない定義、身近なものへの比喩3つ以上、技術的な仕組み",
    "CGM 活用事例: 具体的な導入事例、臨床試験データ、成功事例5つ以上",
    "CGM よくある誤解と実態: 誤解の内容と医学的に正しい理解、専門家の注意点"
  ],
  "angle": "初心者でも理解できる！CGMの仕組みを身近な比喩で徹底解説",
  "curated_topics": null,
  "perplexity_usage": null,
  "gemini_usage_planning": null
}
```

---

## 使用方法

### 1. ファイル作成

上記の仕様に従ってJSONファイルを作成します。

### 2. インポート

Gradio UIの「リサーチデータのインポート」機能を使用:
1. 「📁 リサーチデータをインポート (任意)」セクションでJSONファイルを選択
2. 「リサーチデータをインポート」ボタンをクリック
3. プレビューが表示されたら、「台本を作成」ボタンで台本生成フェーズへ進む

### 3. 検証

システムは以下を自動検証します:
- 必須フィールドの存在
- データ型の正確性
- URLの形式
- `research_mode`の有効性

---

## よくある質問 (FAQ)

### Q1: `research_content`の最適な文字数は？

**A:** 5,000-15,000文字を推奨します。短すぎると台本が薄くなり、長すぎるとLLMのコンテキスト制限に達する可能性があります。

### Q2: 外部AIで`research_content`を生成する際のプロンプト例は？

**A:**
```
あなたはリサーチ専門家です。以下のテーマについて、詳細なリサーチレポートを作成してください。

テーマ: [ここにテーマを入力]

要件:
- 文字数: 10,000文字以上
- 構造: Markdown形式で見出し (##, ###) を使用
- 内容: 専門用語の定義、具体例、数値データ、比喩表現を含む
- 多角性: 複数の視点・側面を網羅
- 引用: 重要な情報には出典を明記 ([1], [2]など)

以下の観点を含めてください:
1. 基本的な定義と概要
2. 身近なものへの比喩 (3つ以上)
3. 技術的な仕組み・構造
4. 活用事例・成功事例
5. よくある誤解と実態
6. 最新の研究動向・将来展望
```

### Q3: `research_sources`が見つからない場合は？

**A:** 空配列 `[]` でも動作しますが、YouTube概要欄に参考文献が表示されません。最低5件の信頼できるソースを含めることを推奨します。

### Q4: `research_mode`はどれを選べばいい？

**A:**
- **初心者向け・教育的:** `lecture`
- **議論・多角的視点:** `debate`
- **実例・体験談:** `voices`
- **雑学・トリビア:** `trivia`
- **最新ニュース:** `weekly_digest`

---

## バリデーションチェックリスト

外部作成したJSONファイルが以下の条件を満たしているか確認してください:

- [ ] 全ての必須フィールドが存在する
- [ ] `session_id`が一意である
- [ ] `theme`が具体的で明確である
- [ ] `research_mode`が有効な値である (`lecture`, `debate`, `voices`, `trivia`, `weekly_digest`)
- [ ] `created_at`がISO 8601形式である
- [ ] `research_content`が5,000文字以上である
- [ ] `research_content`がMarkdown形式で構造化されている
- [ ] `research_sources`が最低5件含まれている
- [ ] 各`research_sources`の`url`が有効なHTTP/HTTPS URLである
- [ ] `queries`が3-5件含まれている
- [ ] `angle`が明確な切り口を示している
- [ ] JSONが有効な形式である (構文エラーがない)

---

## トラブルシューティング

### エラー: "必須フィールドが不足しています"

**原因:** 必須フィールド (`session_id`, `theme`, `research_mode`など) が欠けている

**解決策:** 上記の「必須フィールド」をすべて含めてください

### エラー: "research_modeが無効です"

**原因:** `research_mode`の値が有効な値でない

**解決策:** `lecture`, `debate`, `voices`, `trivia`, `weekly_digest`のいずれかを使用してください

### エラー: "JSONパースエラー"

**原因:** JSON構文エラー (カンマ忘れ、引用符の不一致など)

**解決策:** JSONバリデーターでチェックしてください (例: https://jsonlint.com/)

---

## 技術仕様

### Pydanticモデル定義

このJSON構造は以下のPydanticモデルで定義されています:

**ファイル:** `core/models/artifacts.py`

```python
class ResearchBrief(BaseModel):
    session_id: str
    theme: str
    research_mode: str
    created_at: str
    research_content: str
    research_sources: List[dict]
    queries: List[str]
    angle: str
    curated_topics: Optional[List[dict]] = None
    perplexity_usage: Optional[dict] = None
    gemini_usage_planning: Optional[dict] = None
```

---

## 更新履歴

| バージョン | 日付 | 変更内容 |
|----------|------|---------|
| 3.5.0 | 2026-04-12 | 初版作成 |

---

## 関連ドキュメント

- [マルチLLMガイド](./MULTI_LLM_GUIDE.md)

---

## サポート

質問や問題がある場合は、プロジェクトのIssueトラッカーで報告してください。
