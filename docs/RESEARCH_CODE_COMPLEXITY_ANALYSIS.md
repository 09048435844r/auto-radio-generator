# 案3（research.json廃止）のコード複雑化解決への寄与分析

**調査日:** 2026-04-15  
**目的:** `research.json`を廃止して`research_brief.json`に統一することで、コードの複雑化がどの程度解決されるかを評価

---

## 調査結果サマリー

### 結論
**案3は、コードの複雑化解決に対して「中程度の寄与」があります。**

**評価: ★★★☆☆ (3/5)**

- ✅ データモデルの重複を解消（2つの`ResearchResult`を1つに統一）
- ✅ ファイル保存処理の統一（2箇所の保存ロジックを1箇所に）
- ⚠️ 変更箇所が多い（17ファイル、約6,426行に影響）
- ⚠️ 後方互換性の問題（既存の`research.json`が使えなくなる）
- ❌ 根本的な複雑性の原因は解決しない（フェーズ分離アーキテクチャは維持）

---

## 現状の複雑性の分析

### 1. データモデルの重複

**問題:** 2つの`ResearchResult`クラスが存在

#### `ResearchResult` (dataclass) - 主流

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

**使用箇所:** 12ファイル
- `workflow.py`
- `services/research/perplexity_client.py`
- `services/script_generation/gemini_client.py`
- `services/script_generation/ollama_client.py`
- `services/script_generation/openai_client.py`
- `services/script_generation/orchestrator.py`
- `services/script_generation/topic_curator.py`
- `services/script_generation/metadata_generator.py`
- `services/script_generation/segment_generator.py`
- `services/pipeline/scripting_phase.py`
- `app.py`
- その他

---

#### `ResearchResult` (Pydantic) - 未使用

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

**使用箇所:** 0ファイル（ほぼ未使用）

**問題点:**
- 同名のクラスが2つ存在 → 混乱の原因
- Pydantic版は定義されているが使われていない → デッドコード
- 開発者がどちらを使うべきか迷う

---

### 2. ファイル保存処理の重複

**問題:** 2種類のリサーチデータを2箇所で保存

#### 保存箇所1: `research.json` の保存

**ファイル:** `workflow.py`

```python
def _save_research_to_json(
    research_data: ResearchResult,
    output_dir: Path,
    callbacks
):
    research_path = output_dir / "research.json"
    research_dict = _to_json_safe(asdict(research_data))
    json_str = json.dumps(research_dict, ensure_ascii=False, indent=2)
    research_path.write_text(json_str, encoding="utf-8")
```

**呼び出し箇所:** 2箇所
- `workflow.py:1006` (generate_radio_video_workflow)
- `workflow.py:1214` (generate_radio_video_workflow - 2-Story Mode)

---

#### 保存箇所2: `research_brief.json` の保存

**ファイル:** `services/pipeline/research_phase.py`

```python
def execute_research_phase(...):
    # ...
    research_brief = ResearchBrief(
        session_id=session_manager.session_id,
        theme=theme,
        research_mode=mode,
        created_at=datetime.now().isoformat(),
        research_content=combined_content,
        research_sources=[s.model_dump() for s in all_sources],
        queries=queries,
        angle=angle,
        curated_topics=curated_topics_dict,
        perplexity_usage=perplexity_usage_dict,
        gemini_usage_planning=gemini_usage_dict,
    )
    session_manager.save_research_brief(research_brief)
```

**呼び出し箇所:** 1箇所
- `services/pipeline/research_phase.py:98`

**問題点:**
- 同じリサーチデータを2つの異なる形式で保存
- 保存ロジックが2箇所に分散
- データの同期が取れない可能性

---

### 3. データ変換処理の複雑性

**問題:** `ResearchBrief` ↔ `ResearchResult` の変換が必要

#### 変換箇所1: ResearchBrief → ResearchResult

**ファイル:** `services/pipeline/scripting_phase.py`

```python
def execute_scripting_phase(research_brief: ResearchBrief, ...):
    # ResearchBrief から ResearchSource オブジェクトを復元
    sources = [
        ResearchSource(**source_dict)
        for source_dict in research_brief.research_sources
    ]
    
    # ResearchResult に変換
    research_data = ResearchResult(
        topic=research_brief.theme,
        mode=research_brief.research_mode,
        content=research_brief.research_content,
        sources=sources,
        usage=None
    )
```

**変換箇所2: ResearchBrief → ResearchResult (インポート時)**

**ファイル:** `workflow.py`

```python
# research_import_filepath が指定された場合
with open(research_import_filepath, 'r', encoding='utf-8') as _f:
    _brief_data = _json.load(_f)
brief = ResearchBrief(**_brief_data)

# ResearchResult に変換
preloaded_research = ResearchResult(
    topic=brief.theme,
    mode=brief.research_mode,
    content=brief.research_content,
    sources=imported_sources,
    usage=None
)
```

**問題点:**
- 同じデータを2つの形式で扱う必要がある
- 変換ロジックが複数箇所に分散
- フィールド名の不一致（`theme` vs `topic`, `research_content` vs `content`）

---

## 案3実装による改善効果

### ✅ 改善される点

#### 1. データモデルの統一

**変更前:**
```
ResearchResult (dataclass) - 主流
ResearchResult (Pydantic) - 未使用
ResearchBrief (Pydantic) - フェーズ間の受け渡し
```

**変更後:**
```
ResearchBrief (Pydantic) - 唯一のリサーチデータモデル
```

**効果:**
- ✅ データモデルが1つに統一される
- ✅ `ResearchResult` (dataclass) を削除できる
- ✅ `ResearchResult` (Pydantic) を削除できる
- ✅ 開発者の混乱が減る

**削減されるコード:**
- `core/interfaces/researcher.py`: `ResearchResult` クラス定義（約10行）
- `core/models/research.py`: `ResearchResult` クラス定義（約40行）
- 合計: 約50行

---

#### 2. ファイル保存処理の統一

**変更前:**
```
workflow.py: _save_research_to_json() → research.json
research_phase.py: save_research_brief() → research_brief.json
```

**変更後:**
```
research_phase.py: save_research_brief() → research_brief.json
```

**効果:**
- ✅ 保存処理が1箇所に統一される
- ✅ `_save_research_to_json()` 関数を削除できる
- ✅ 保存ロジックの重複が解消される

**削減されるコード:**
- `workflow.py`: `_save_research_to_json()` 関数（約30行）
- `workflow.py`: 呼び出し箇所（2箇所、約10行）
- 合計: 約40行

---

#### 3. データ変換処理の削減

**変更前:**
```
ResearchBrief → ResearchResult 変換（2箇所）
```

**変更後:**
```
変換不要（すべて ResearchBrief で統一）
```

**効果:**
- ✅ 変換ロジックが不要になる
- ✅ フィールド名の不一致が解消される
- ✅ データの整合性が保たれる

**削減されるコード:**
- `scripting_phase.py`: 変換ロジック（約15行）
- `workflow.py`: 変換ロジック（約20行）
- 合計: 約35行

---

### ⚠️ 変更が必要な箇所

#### 影響を受けるファイル: 17ファイル

| ファイル | 変更内容 | 行数（推定） |
|---------|---------|------------|
| `core/interfaces/researcher.py` | `ResearchResult` 削除 | -10 |
| `core/models/research.py` | `ResearchResult` 削除 | -40 |
| `workflow.py` | `_save_research_to_json()` 削除、型変更 | -50, +20 |
| `services/research/perplexity_client.py` | 戻り値を `ResearchBrief` に変更 | +30 |
| `services/script_generation/gemini_client.py` | 引数型を `ResearchBrief` に変更 | +10 |
| `services/script_generation/ollama_client.py` | 引数型を `ResearchBrief` に変更 | +10 |
| `services/script_generation/openai_client.py` | 引数型を `ResearchBrief` に変更 | +10 |
| `services/script_generation/orchestrator.py` | 引数型を `ResearchBrief` に変更 | +10 |
| `services/script_generation/topic_curator.py` | 引数型を `ResearchBrief` に変更 | +10 |
| `services/script_generation/metadata_generator.py` | 引数型を `ResearchBrief` に変更 | +10 |
| `services/script_generation/segment_generator.py` | 引数型を `ResearchBrief` に変更 | +10 |
| `services/pipeline/scripting_phase.py` | 変換ロジック削除 | -15 |
| `app.py` | 型変更 | +10 |
| `tests/mock_data/research.json` | ファイル形式変更 | - |
| その他 | 型アノテーション修正 | +20 |

**合計:**
- 削減: 約125行
- 追加: 約150行
- **正味: +25行（ほぼ同じ）**

---

### ❌ 改善されない点

#### 1. フェーズ分離アーキテクチャの複雑性

**問題:** リサーチフェーズと台本作成フェーズが分離されている

```
リサーチフェーズ
  ↓ (ResearchBrief を保存)
workspace/[session_id]/research_brief.json
  ↓ (ResearchBrief を読み込み)
台本作成フェーズ
```

**案3実装後も:**
- ✅ データモデルは統一される
- ❌ フェーズ分離の複雑性は残る
- ❌ ファイルの読み書きは依然として必要

---

#### 2. インポート機能の複雑性

**問題:** 外部ファイルのインポート処理

**案3実装後も:**
- ❌ インポート処理は依然として必要
- ❌ ファイル形式のバリデーションは依然として必要
- ❌ エラーハンドリングは依然として必要

---

#### 3. 後方互換性の問題

**問題:** 既存の `research.json` (165ファイル) が使えなくなる

**対策が必要:**
- 変換スクリプトの作成
- ドキュメントの更新
- ユーザーへの周知

---

## コード複雑性の定量評価

### 現状の複雑性指標

| 指標 | 値 |
|-----|-----|
| **データモデル数** | 3つ (ResearchResult × 2, ResearchBrief × 1) |
| **保存処理の箇所** | 2箇所 (research.json, research_brief.json) |
| **変換処理の箇所** | 2箇所 (ResearchBrief → ResearchResult) |
| **影響を受けるファイル数** | 17ファイル |
| **リサーチ関連コード行数** | 6,426行 (全体の0.3%) |

---

### 案3実装後の複雑性指標

| 指標 | 変更前 | 変更後 | 改善率 |
|-----|-------|-------|-------|
| **データモデル数** | 3つ | 1つ | **-67%** ✅ |
| **保存処理の箇所** | 2箇所 | 1箇所 | **-50%** ✅ |
| **変換処理の箇所** | 2箇所 | 0箇所 | **-100%** ✅ |
| **影響を受けるファイル数** | 17ファイル | 17ファイル | **0%** ⚠️ |
| **リサーチ関連コード行数** | 6,426行 | 6,451行 | **+0.4%** ⚠️ |

---

## 複雑性の根本原因

### 真の複雑性の原因

**案3では解決されない根本的な問題:**

1. **フェーズ分離アーキテクチャ**
   - リサーチフェーズと台本作成フェーズが独立
   - フェーズ間でデータの受け渡しが必要
   - ファイルの読み書きが必要

2. **複数のLLMプロバイダー対応**
   - Gemini, OpenAI, Anthropic, Ollama
   - 各プロバイダーごとに異なるクライアント実装
   - 共通インターフェースの維持が必要

3. **オーケストレーター機能**
   - トピックキュレーション
   - セグメント生成
   - メタデータ生成
   - 各機能が独立したモジュール

**これらは設計上の意図的な複雑性であり、削減すべきではない**

---

## 総合評価

### コード複雑化解決への寄与度: ★★★☆☆ (3/5)

#### ✅ 改善される点（寄与度: 高）

1. **データモデルの統一** (★★★★★)
   - 3つのモデル → 1つのモデル
   - 混乱の解消
   - デッドコードの削除

2. **保存処理の統一** (★★★★☆)
   - 2箇所 → 1箇所
   - ロジックの重複解消

3. **変換処理の削減** (★★★★☆)
   - 変換ロジックが不要に
   - フィールド名の不一致解消

#### ⚠️ 変更が必要な点（コスト: 中）

4. **17ファイルの修正** (★★★☆☆)
   - 型アノテーションの変更
   - 約150行の追加
   - テストの更新

5. **後方互換性の問題** (★★☆☆☆)
   - 既存の165ファイルが使えなくなる
   - 変換スクリプトが必要

#### ❌ 改善されない点（限界）

6. **根本的な複雑性は残る** (★☆☆☆☆)
   - フェーズ分離アーキテクチャは維持
   - ファイルの読み書きは依然として必要
   - インポート機能の複雑性は残る

---

## 推奨

### 案3を実装すべきか？

**コード複雑化解決の観点から: 条件付きで推奨**

#### 推奨する条件:

1. ✅ データモデルの統一を優先する場合
2. ✅ 長期的なメンテナンス性を重視する場合
3. ✅ 新規プロジェクトまたはリファクタリングのタイミング

#### 推奨しない条件:

1. ❌ 短期的な開発速度を優先する場合
2. ❌ 既存のデータ資産を保護したい場合
3. ❌ 後方互換性を重視する場合

---

## 代替案との比較

| 案 | 複雑性削減 | 実装コスト | 後方互換性 | 総合評価 |
|----|----------|----------|----------|---------|
| **案1: 両方保存** | ★☆☆☆☆ | ★★★★★ | ★★★★★ | ★★★★☆ |
| **案2: インポート拡張** | ★★☆☆☆ | ★★★☆☆ | ★★★★★ | ★★★★☆ |
| **案3: research.json廃止** | ★★★☆☆ | ★★☆☆☆ | ★☆☆☆☆ | ★★★☆☆ |

**結論:**
- **インポート機能の実用性**: 案1 > 案2 > 案3
- **コード複雑性の削減**: 案3 > 案2 > 案1
- **総合的なバランス**: 案1 ≈ 案2 > 案3

---

## 実装状況

### ✅ 実装済み: 案1 - 両方のファイルを保存

**実装日:** 2026-04-15

自動モードで生成したリサーチデータを再利用可能にするため、`research_brief.json`も保存するように実装しました。

**実装箇所:**
- `workflow.py`: 通常モードと2-Story Modeの両方

**効果:**
- ✅ インポート機能が即座に使える
- ✅ 後方互換性を完全に維持
- ⚠️ ディスク使用量は微増（+10 MB程度、全体の0.08%）

---

## 将来の改善案

### 📋 案2と案3の詳細

将来的な改善案（案2: インポート機能の拡張、案3: research.json の段階的廃止）については、以下のドキュメントを参照してください。

**詳細:** [リサーチデータ統一の将来的な改善案](./RESEARCH_DATA_FUTURE_IMPROVEMENTS.md)

---

## 最終推奨

### **ベストプラクティス: 段階的アプローチ**

**フェーズ1: 案1を実装（完了）** ✅
- `research_brief.json` も保存
- インポート機能が使えるようになる
- 複雑性は微増（+10 MB、+10行程度）

**フェーズ2: 案2を実装（中期）**
- インポート機能を拡張
- `research.json` も受け入れる
- ユーザビリティ向上

**フェーズ3: 案3を検討（長期）**
- データモデルの統一
- `research.json` の段階的廃止
- 十分なデータ移行期間を設ける

**この段階的アプローチのメリット:**
- ✅ 即座にインポート機能が使える
- ✅ 後方互換性を保ちながら改善
- ✅ 長期的にはコードの複雑性を削減
- ✅ ユーザーへの影響を最小化

---

## 関連ドキュメント

- [リサーチデータ統一の将来的な改善案](./RESEARCH_DATA_FUTURE_IMPROVEMENTS.md) - 案2と案3の詳細実装計画
- [リサーチファイル調査報告](./RESEARCH_FILE_INVESTIGATION.md) - research.jsonとresearch_brief.jsonの違い
- [リサーチデータJSON仕様書](./RESEARCH_BRIEF_SPECIFICATION.md) - ResearchBriefの仕様
