# research_brief.json と research.json の調査報告

**調査日:** 2026-04-15  
**目的:** `research_brief.json`と`research.json`の違いを調査し、統一の可能性を検討する

---

## 調査結果サマリー

### 結論
**`research_brief.json`と`research.json`は異なるファイルです。**

- **用途が異なる**: 保存場所、データ構造、使用目的が完全に異なる
- **統一は不適切**: それぞれ独自の役割があり、両方とも必要

---

## 詳細比較

### 1. ファイルの保存場所

| ファイル名 | 保存場所 | 例 |
|-----------|---------|-----|
| `research_brief.json` | `workspace/[session_id]/` | `workspace/20260412_165103/research_brief.json` |
| `research.json` | `output/[session_id]/` | `output/20260220_190000/research.json` |

**発見:**
- `research_brief.json`: 46件（workspace配下）
- `research.json`: 59件（output配下）

---

### 2. データ構造の違い

#### `research_brief.json` の構造

**データモデル:** `ResearchBrief` (Pydantic)  
**ファイル:** `core/models/artifacts.py`

**フィールド:**
```json
{
  "session_id": "20260412_165103",
  "theme": "内臓脂肪について",
  "research_mode": "lecture",
  "created_at": "2026-04-12T16:51:03.123456",
  "research_content": "...",
  "research_sources": [...],
  "queries": [...],
  "angle": "...",
  "curated_topics": null,
  "perplexity_usage": {...},
  "gemini_usage_planning": {...}
}
```

**特徴:**
- **11フィールド**: 包括的なリサーチ成果物
- **Pydanticモデル**: 型安全、バリデーション付き
- **用途**: 台本作成フェーズへの入力（フェーズ間の中間成果物）

---

#### `research.json` の構造

**データモデル:** `ResearchResult` (dataclass)  
**ファイル:** `core/interfaces/researcher.py`

**フィールド:**
```json
{
  "topic": "鼻うがいについて",
  "mode": "lecture",
  "content": "...",
  "sources": [...],
  "usage": {...}
}
```

**特徴:**
- **5フィールド**: シンプルなリサーチ結果
- **dataclass**: 軽量、実行時のデータ構造
- **用途**: 最終出力ディレクトリへの保存（アーカイブ・参照用）

---

### 3. 使用目的の違い

#### `research_brief.json`

**目的:** **フェーズ間の中間成果物（パイプライン分離アーキテクチャ）**

**使用箇所:**
1. **リサーチフェーズの出力**
   - `services/pipeline/research_phase.py`: リサーチ完了後に保存
   - `SessionManager.save_research_brief()`: workspace配下に保存

2. **台本作成フェーズの入力**
   - `services/pipeline/scripting_phase.py`: `ResearchBrief`を読み込んで台本生成
   - `SessionManager.load_research_brief()`: workspace配下から読み込み

3. **外部インポート機能**
   - `app_hitl_handlers.py`: 外部作成した`research_brief.json`をインポート
   - UIの「リサーチデータのインポート」機能で使用

**ライフサイクル:**
```
リサーチフェーズ
  ↓ (保存)
workspace/[session_id]/research_brief.json
  ↓ (読み込み)
台本作成フェーズ
```

---

#### `research.json`

**目的:** **最終出力ディレクトリへのアーカイブ（参照・デバッグ用）**

**使用箇所:**
1. **最終出力時の保存**
   - `workflow.py`: `_save_research_to_json()` で保存
   - 動画生成完了後、output配下に保存

2. **モックデータ**
   - `services/research/perplexity_client.py`: `tests/mock_data/research.json`を読み込み
   - 開発・テスト時のモックデータとして使用

**ライフサイクル:**
```
リサーチフェーズ
  ↓ (完了後)
output/[session_id]/research.json
  ↓ (アーカイブ)
参照・デバッグ用
```

---

### 4. データモデルの重複問題

**問題:** 2つの異なる`ResearchResult`クラスが存在

#### `ResearchResult` (dataclass) - 旧型

**ファイル:** `core/interfaces/researcher.py`

```python
@dataclass
class ResearchResult:
    topic: str
    mode: ResearchMode
    content: str
    sources: list[ResearchSource] | None = None
    usage: "PerplexityUsage | None" = None
```

**使用箇所:**
- `workflow.py`: `research.json`の保存
- `services/research/perplexity_client.py`: リサーチ結果の返り値
- `app.py`: マニュアル入力時の処理

---

#### `ResearchResult` (Pydantic) - 新型（未使用？）

**ファイル:** `core/models/research.py`

```python
class ResearchResult(BaseModel):
    query: str
    raw_content: str
    sources: List[ResearchSource] = Field(default_factory=list)
    timestamp: Optional[str] = Field(None)
    provider: str = Field(default="perplexity")
    mode: Optional[str] = Field(None)  # 後方互換性
    content: Optional[str] = Field(None)  # 後方互換性
```

**特徴:**
- Pydanticモデル（型安全）
- 後方互換性のための`mode`と`content`フィールド
- **現在ほとんど使用されていない**

---

## 統一の可能性

### 統一は不適切

**理由:**

1. **用途が異なる**
   - `research_brief.json`: フェーズ間の中間成果物（必須）
   - `research.json`: 最終出力のアーカイブ（オプション）

2. **データ構造が異なる**
   - `research_brief.json`: 11フィールド（包括的）
   - `research.json`: 5フィールド（シンプル）

3. **保存場所が異なる**
   - `research_brief.json`: workspace（作業用）
   - `research.json`: output（最終成果物）

4. **ライフサイクルが異なる**
   - `research_brief.json`: 読み書き両方（フェーズ間の受け渡し）
   - `research.json`: 書き込みのみ（アーカイブ）

---

## 推奨アクション

### 1. ファイル名の明確化（不要）

**現状:** ファイル名は既に明確
- `research_brief.json`: "Brief"（要約・概要）を含む → 中間成果物を示唆
- `research.json`: シンプル → 最終成果物を示唆

**結論:** 変更不要

---

### 2. データモデルの整理（推奨）

**問題:** 2つの`ResearchResult`クラスが存在し、混乱を招く

**推奨対策:**

#### オプション1: Pydantic版を削除（推奨）

**理由:**
- `core/models/research.py`の`ResearchResult`はほとんど使用されていない
- `core/interfaces/researcher.py`の`ResearchResult` (dataclass) が主流

**実装:**
```python
# core/models/research.py から ResearchResult を削除
# ResearchSource と ResearchPlan のみ残す
```

#### オプション2: dataclass版をPydanticに統一

**理由:**
- Pydanticは型安全でバリデーション機能がある
- `ResearchBrief`もPydanticなので統一感がある

**実装:**
```python
# core/interfaces/researcher.py の ResearchResult を削除
# core/models/research.py の ResearchResult を使用
# 全ての使用箇所を更新
```

**デメリット:**
- 変更箇所が多い（workflow.py, perplexity_client.py, app.pyなど）
- 後方互換性の問題

---

### 3. ドキュメントの追加（推奨）

**目的:** 開発者が混乱しないように、各ファイルの役割を明記

**実装:**
```markdown
# docs/FILE_STRUCTURE.md

## リサーチ関連ファイル

### research_brief.json
- **場所:** workspace/[session_id]/
- **用途:** フェーズ間の中間成果物
- **データモデル:** ResearchBrief (core/models/artifacts.py)
- **読み書き:** 両方

### research.json
- **場所:** output/[session_id]/
- **用途:** 最終出力のアーカイブ
- **データモデル:** ResearchResult (core/interfaces/researcher.py)
- **読み書き:** 書き込みのみ
```

---

## まとめ

### 質問への回答

**Q: `research_brief.json`と`research.json`の中身は同じものですか？**

**A: いいえ、異なるものです。**

| 項目 | research_brief.json | research.json |
|-----|-------------------|--------------|
| **保存場所** | workspace/ | output/ |
| **フィールド数** | 11 | 5 |
| **用途** | フェーズ間の中間成果物 | 最終出力のアーカイブ |
| **読み書き** | 両方 | 書き込みのみ |
| **データモデル** | ResearchBrief (Pydantic) | ResearchResult (dataclass) |

### 統一の必要性

**統一は不適切です。** それぞれ独自の役割があり、両方とも必要です。

### 推奨アクション

1. ✅ **ファイル名はそのまま維持**
2. ⚠️ **データモデルの整理を検討**（2つの`ResearchResult`クラスの統一）
3. ✅ **ドキュメントの追加**（開発者向けの説明）

---

## 実装状況

### ✅ 実装済み: 案1 - 両方のファイルを保存

**実装日:** 2026-04-15

自動モードで生成したリサーチデータを再利用可能にするため、`research_brief.json`も保存するように実装しました。

**詳細:** [リサーチデータ統一の将来的な改善案](./RESEARCH_DATA_FUTURE_IMPROVEMENTS.md)

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `core/models/artifacts.py` | ResearchBrief (Pydantic) の定義 |
| `core/interfaces/researcher.py` | ResearchResult (dataclass) の定義 |
| `core/models/research.py` | ResearchResult (Pydantic) の定義（未使用？） |
| `core/session_manager.py` | research_brief.json の読み書き |
| `workflow.py` | research.json と research_brief.json の保存 |
| `services/pipeline/research_phase.py` | ResearchBrief の生成 |
| `services/pipeline/scripting_phase.py` | ResearchBrief の読み込み |

---

## 関連ドキュメント

- [リサーチデータ統一の将来的な改善案](./RESEARCH_DATA_FUTURE_IMPROVEMENTS.md) - 案2と案3の詳細
- [コード複雑性分析](./RESEARCH_CODE_COMPLEXITY_ANALYSIS.md) - 各案の複雑性への影響
- [リサーチデータJSON仕様書](./RESEARCH_BRIEF_SPECIFICATION.md) - ResearchBriefの仕様
