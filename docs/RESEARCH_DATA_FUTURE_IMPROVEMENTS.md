# リサーチデータ統一の将来的な改善案

**作成日:** 2026-04-15  
**ステータス:** 将来の実装候補  
**関連:** `research.json` と `research_brief.json` の統一

---

## 現状（案1実装済み）

### 実装済み: 案1 - 両方のファイルを保存

**実装日:** 2026-04-15

**概要:**
- 自動モードで生成したリサーチデータを再利用可能にするため、`research_brief.json`も保存
- `research.json`は既存の参照用として維持

**実装箇所:**
- `workflow.py`: `_save_research_to_json()` 内
- 通常モードと2-Story Modeの両方で実装

**効果:**
- ✅ 自動モードで生成したリサーチデータをインポート機能で再利用可能
- ✅ 既存の`research.json`参照箇所は影響を受けない
- ✅ 後方互換性を完全に維持
- ⚠️ ディスク使用量は微増（+10 MB程度、全体の0.08%）

**ファイル構造:**
```
output/[session_id]/
  ├── research.json           # 既存（5フィールド、シンプル）
  ├── research_brief.json     # 新規（11フィールド、包括的）★
  ├── research_report.md
  └── full_research_report.md
```

---

## 将来の改善案

### 案2: インポート機能の拡張（中期実装候補）

**優先度:** ★★★★☆  
**実装難易度:** ⭐⭐⭐☆☆  
**推定工数:** 2-3日

#### 概要

インポート機能を拡張して、`research.json`（5フィールド）も受け入れられるようにする。

#### 目的

- 既存の165ファイルの`research.json`を再利用可能にする
- ユーザーがファイル形式を意識せずにインポートできる
- 後方互換性を最大化

#### 実装内容

**1. ファイル形式の自動判定**

```python
# app_hitl_handlers.py の hitl_import_research() 内

def _detect_research_file_format(data: dict) -> str:
    """リサーチファイルの形式を判定
    
    Returns:
        "research_brief" or "research_json"
    """
    # research_brief.json の特徴: session_id, theme, research_content
    if "session_id" in data and "theme" in data and "research_content" in data:
        return "research_brief"
    
    # research.json の特徴: topic, content (session_id なし)
    elif "topic" in data and "content" in data and "session_id" not in data:
        return "research_json"
    
    else:
        raise ValueError("Unknown research file format")
```

**2. research.json → ResearchBrief への変換**

```python
def _convert_research_to_brief(data: dict, session_id: str) -> ResearchBrief:
    """research.json を ResearchBrief に変換
    
    Args:
        data: research.json の内容
        session_id: 新規セッションID
    
    Returns:
        ResearchBrief: 変換されたブリーフ
    """
    return ResearchBrief(
        session_id=session_id,
        theme=data["topic"],
        research_mode=data.get("mode", "lecture"),
        created_at=datetime.now().isoformat(),
        research_content=data["content"],
        research_sources=data.get("sources", []),
        queries=[data["topic"]],  # topicをクエリとして使用
        angle="インポートデータ（自動生成）",
        curated_topics=None,
        perplexity_usage=data.get("usage"),
        gemini_usage_planning=None
    )
```

**3. インポート処理の統合**

```python
async def hitl_import_research(filepath: str | None, progress=gr.Progress()):
    # ファイル読み込み
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 形式判定
    file_format = _detect_research_file_format(data)
    
    # 新規セッション作成
    session_manager = SessionManager(..., session_id=None)
    
    # 形式に応じて処理
    if file_format == "research_brief":
        # 既存の処理
        research_brief = ResearchBrief(**data)
    else:  # research_json
        # 変換処理
        research_brief = _convert_research_to_brief(data, session_manager.session_id)
        logger.info(f"research.json を ResearchBrief に変換しました")
    
    # 保存
    research_brief_path = session_manager.session_dir / "research_brief.json"
    with open(research_brief_path, 'w', encoding='utf-8') as f:
        json.dump(research_brief.model_dump(), f, ensure_ascii=False, indent=2)
    
    # プレビュー表示
    # ...
```

#### メリット

- ✅ 既存の165ファイルがすべて再利用可能
- ✅ ユーザーがファイル形式を意識しなくて良い
- ✅ 後方互換性が最大化
- ✅ UIの変更不要

#### デメリット

- ⚠️ 変換ロジックが必要（欠損フィールドの補完）
- ⚠️ `queries`, `angle` などの情報が失われる可能性
- ⚠️ テストケースの追加が必要

#### 実装ファイル

- `app_hitl_handlers.py`: インポート処理の拡張
- `tests/test_import_research.py`: テストケースの追加

---

### 案3: research.json の段階的廃止（長期実装候補）

**優先度:** ★★☆☆☆  
**実装難易度:** ⭐⭐⭐⭐☆  
**推定工数:** 5-7日

#### 概要

`research.json`を段階的に廃止し、`research_brief.json`に完全統一する。

#### 目的

- データモデルの重複を解消（2つの`ResearchResult`を1つに統一）
- 保存処理の統一（2箇所→1箇所）
- 変換処理の削減（ResearchBrief ↔ ResearchResult 変換が不要に）
- コードの複雑性を削減

#### 実装内容

**フェーズ1: データモデルの統一**

1. `core/interfaces/researcher.py`の`ResearchResult` (dataclass) を削除
2. `core/models/research.py`の`ResearchResult` (Pydantic) を削除
3. すべての箇所で`ResearchBrief`を使用

**影響を受けるファイル（17ファイル）:**
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

**フェーズ2: 保存処理の統一**

1. `workflow.py`の`_save_research_to_json()`関数を削除
2. `research.json`の保存を停止
3. `research_brief.json`のみ保存

**フェーズ3: 変換処理の削減**

1. `scripting_phase.py`の変換ロジックを削除
2. `workflow.py`の変換ロジックを削除

**フェーズ4: 移行期間の設定**

1. 既存の`research.json`を`research_brief.json`に一括変換するスクリプトを提供
2. ドキュメントの更新
3. ユーザーへの周知（6ヶ月の移行期間）

#### メリット

- ✅ データモデルが1つに統一される（複雑性-67%）
- ✅ 保存処理が1箇所に統一される（複雑性-50%）
- ✅ 変換処理が不要になる（複雑性-100%）
- ✅ 長期的なメンテナンス性が向上

#### デメリット

- ❌ 実装コストが高い（17ファイルの修正）
- ❌ 後方互換性の問題（既存の165ファイルが使えなくなる）
- ❌ テストの大幅な更新が必要
- ❌ ユーザーへの影響が大きい

#### 実装の前提条件

1. ✅ 案1が実装済み（新規データは`research_brief.json`を含む）
2. ✅ 案2が実装済み（既存データのインポートが可能）
3. ✅ 十分な移行期間（6ヶ月以上）
4. ✅ ユーザーへの事前周知

#### 実装ファイル

- `core/interfaces/researcher.py`: `ResearchResult`削除
- `core/models/research.py`: `ResearchResult`削除
- `workflow.py`: `_save_research_to_json()`削除、型変更
- `services/research/perplexity_client.py`: 戻り値型変更
- `services/script_generation/*.py`: 引数型変更（9ファイル）
- `services/pipeline/scripting_phase.py`: 変換ロジック削除
- `app.py`: 型変更
- `scripts/convert_research_to_brief.py`: 一括変換スクリプト（新規）
- `tests/*.py`: テストケース更新

---

## 実装の推奨順序

### 短期（完了）

- [x] **案1: 両方のファイルを保存** (2026-04-15実装済み)
  - インポート機能が即座に使える
  - 後方互換性を完全に維持

### 中期（6ヶ月以内）

- [ ] **案2: インポート機能の拡張**
  - 既存の`research.json`も再利用可能に
  - ユーザビリティ向上
  - 実装難易度: 中

### 長期（1年以上）

- [ ] **案3: research.json の段階的廃止**
  - データモデルの統一
  - コードの複雑性削減
  - 十分な移行期間を設ける
  - 実装難易度: 高

---

## 意思決定の基準

### 案2を実装すべきタイミング

- ✅ 既存の`research.json`を再利用したいという要望が増えた場合
- ✅ インポート機能の使用頻度が高まった場合
- ✅ 開発リソースに余裕がある場合

### 案3を実装すべきタイミング

- ✅ コードの複雑性が問題になった場合
- ✅ データモデルの重複がバグの原因になった場合
- ✅ 大規模なリファクタリングのタイミング
- ✅ メジャーバージョンアップのタイミング

### 案3を実装すべきでないタイミング

- ❌ 短期的な開発速度を優先する場合
- ❌ 後方互換性を重視する場合
- ❌ ユーザーへの影響を最小化したい場合

---

## 参考資料

- [リサーチファイル調査報告](./RESEARCH_FILE_INVESTIGATION.md)
- [コード複雑性分析](./RESEARCH_CODE_COMPLEXITY_ANALYSIS.md)
- [リサーチデータJSON仕様書](./RESEARCH_BRIEF_SPECIFICATION.md)

---

## 更新履歴

| 日付 | 内容 |
|------|------|
| 2026-04-15 | 初版作成、案1実装完了 |
