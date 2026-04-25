# Backlog

レビュー・実装過程で発見された技術的負債や将来対応項目のログ。
Append-Only: 既存エントリは編集・削除せず、末尾に追記する。

---

## [BACKLOG] ShowRunnerConfig.enabled の SSOT 不整合

**記録日**: 2026-04-23
**発見経緯**: Phase 4 施策③ FactExtractor のレビュー対応 PR-A (ブランチ: `review/phase4-fact-extractor-a`) 作業中に判明

### 問題
FactExtractorConfig と同型の SSOT 三者不整合が ShowRunnerConfig にも存在する:

- `core/models/config.py`: `ShowRunnerConfig.enabled` の既定値は `False`
- `config.yaml` (shipped): `show_runner.enabled` は `true`
- docstring/コメントは Pydantic モデル側の既定値を前提とした記述（"既定は enabled=False で、有効化しない限り従来通りの動作"）

同一モジュール内の `FactExtractorConfig` については PR-A で `default=True` + SSOT 宣言 docstring に統一済み。ShowRunnerConfig だけが旧状態のまま取り残されている。

### 推奨対応
PR-A で採用した方針と同じく、docstring/コード側を現実 (shipped config) に合わせて `enabled=True` に統一し、docstring に SSOT 宣言を追記する。これにより Phase 3 施策④のロールアウト状態が「デフォルト有効」として明文化される。

想定される変更範囲:
- `core/models/config.py` の `ShowRunnerConfig` クラス（`default=True` + docstring 改訂）
- 必要なら `config.yaml` の `show_runner` 周りのコメントも SSOT 文言に整合

### 優先度
中。実害は顕在化していないが、SSOT 原則違反が残り続けるのは技術的負債。Gate 2b 完了後、または FactExtractor PR-B と同時期の対応を想定。

### スコープ外になった理由
PR-A の Guardrails で「スコープ外指摘 (#3, #4, #8, #9, #10) には一切触らない」と明示指示されており、ShowRunnerConfig は #1 (FactExtractorConfig) の類似問題ではあるが別モデル・別 Phase の管轄のため、スコープ厳守を優先して記録に留めた。

---

## [BACKLOG] ExtractedFact.category の実データ分布調査

**記録日**: 2026-04-23
**発見経緯**: PR-B (`review/phase4-fact-extractor-b`) の #8 対応時、実データ 0 件のため分布調査を見送ったことによる

### 内容
PR-B では `config/prompts.yaml` の 6 カテゴリ（数値／人物／事件／比較／引用／その他）を SSOT として `FactCategory = Literal[...]` で型固定する戦略を採用した。しかし実運用開始後、LLM が想定外の category 値を返して `_DEFAULT_FACT_CATEGORY = "その他"` にフォールバックする頻度を調査する必要がある。

### 発動条件
`fact_sheet.json` が数十件程度蓄積した時点（当面は該当ファイル 0 件のため着手不可）。

### 調査観点
- ログに残した warning「`[FactExtractor] Unknown category 'X' (not in SSOT [...]); normalizing to 'その他'.`」の頻度集計
- 頻出する未知値があれば、SSOT（`config/prompts.yaml` + `core/models/fact_sheet.py::FactCategory`）への追加 or プロンプト文言改善を検討
- Literal の拡張要否判断（例: 「引用」を「専門家発言」「研究結果」に分割すべきか等）

### 優先度
低（運用データ蓄積待ち）。PR-B で入れた防御層（warning + フォールバック）により、未知カテゴリでもシステム障害は起きない。

---

## [BACKLOG] PR-E（プロンプト明示圧力強化）の実運用効果観察

**記録日**: 2026-04-24
**発見経緯**: PR-E（`review/issue-B-prompt-pressure`）でプロンプトを改修したが、効果はオフラインでは検証不能（LLM 実呼び出しが必要）

### 内容
PR-E は以下 2 箇所でプロンプト明示圧力を強化した:
- TopicCurator: `title` に必須化 + 20〜40 文字 + 数値/固有名詞含む + 良い例/悪い例
- FactExtractor: `facts` 最低 5 件 + 意外性スコア 4〜6 積極採用 + 日本語医療系例示 + `extractor_reasoning` 空文字禁止

これらが qwen3:8b に対して有効だったか、1 日 1 回の本運用セッションで効果観察する。

### 発動条件
PR-E を含む一連の変更を push/merge して本運用に投入した後、数セッション分のログ蓄積後。

### 観察項目（PR-C の logger 収集により追跡可能）
1. `[WARNING] [...] LLM omitted 'title'` の発生頻度（PR-E 前は本運用で発生）
2. `fact_sheet.json` の `facts` 件数分布（PR-E 前は 0 件記録あり）
3. `fact_sheet.json` の `extractor_reasoning` 空文字率
4. Curator の合成タイトル品質（20〜40 文字・数値/固有名詞含む基準を満たすか）

### 判断基準
- 3〜5 セッションで上記 warning 頻度が低下しない場合 → プロンプト再調整 or BACKLOG のモデル変更タスクへエスカレーション
- 効果あり → PR-E の改善手法 (A+B+C / A+B+E) の妥当性が確認される

### 優先度
中（次回本運用セッションで即確認可能）

---

## [BACKLOG] Ollama Structured Output（JSON schema 強制）導入検討

**記録日**: 2026-04-24
**発見経緯**: PR-E のプロンプト改善で効果不十分だった場合の次の一手として、調査報告で挙がった

### 内容
Ollama は `format` パラメータに JSON schema を渡すことで、LLM の出力を schema に物理的に制約できる機能を提供している（2026-04 時点）。プロンプトでの明示圧力（PR-E）はモデル依存で効果が不安定だが、Structured Output は **schema 層で省略を不可能にする** ため、title 欠落や facts=[] を構造的に防げる。

### 実装想定
- `core/interfaces/llm_port.py` の `LLMRequest` に `response_schema: Optional[dict]` フィールド追加
- `services/script_generation/adapters/ollama_adapter.py` で `response_schema` を `format` パラメータに渡す
- 他プロバイダ（Gemini / OpenAI / Anthropic）対応は別フェーズ（JSON mode / response_format の差異吸収）
- 各エージェントの Pydantic モデル（`CuratedTopic` / `ExtractedFact`）から schema を自動生成（`model_json_schema()`）

### 前提条件
- 利用している Ollama バージョン（現状: 不明）での schema サポート確認が必要
- qwen3:8b が `format` 指定下で安定動作するかの実検証が必要

### 優先度
低〜中（PR-E の効果観察結果次第。効果十分なら見送り、不十分なら昇格）

---

## [BACKLOG] モデル変更検討（qwen3:8b → 中型モデル）

**記録日**: 2026-04-24
**発見経緯**: PR-E のプロンプト改善で効果不十分 & Structured Output 導入も不可だった場合の最終手段

### 内容
qwen3:8b はプロンプト遵守力が弱く、本件の title 欠落・facts=[] の根本原因となっている可能性がある。プロンプト改善と Structured Output のいずれも効果不十分な場合、中型モデルへの切替を検討する:
- 候補: qwen3:32b / qwen3:30b-a3b / gemma4:26b / gpt-oss:20b-long
- ただし中型モデルは VRAM 消費・生成時間が増加するため、運用コストとのトレードオフ

### 適用範囲
- TopicCurator / FactExtractor のみ（Curator 系は品質が全体に波及）
- SegmentGenerator はすでに大型モデル（gemma4:26b 等）を使用中、対象外

### 実装
`config.yaml` で各エージェントの `model` フィールドを個別設定するだけで対応可能（PR-A/PR-D で既に config 駆動化済み）。コード変更不要。

### 優先度
低（PR-E + 将来の Structured Output で効果が出れば不要）

---

## [BACKLOG] ユーザープロンプトの SSOT 化（Python コード埋め込みから prompts.yaml へ）

**記録日**: 2026-04-24
**発見経緯**: PR-E（`review/issue-B-prompt-pressure`）でプロンプト改修中に判明

### 問題
本プロジェクトはシステムプロンプトを `config/prompts.yaml` で SSOT 管理する明確な設計思想を持つが、**ユーザープロンプト（JSON 例示・指示文言を含む）は各エージェントの Python ソースに f-string リテラルとして埋め込まれている**。該当箇所:

- `services/script_generation/topic_curator.py::_build_curation_user_prompt`
- `services/script_generation/fact_extractor.py::_build_fact_extractor_user_prompt`
- `services/script_generation/show_runner.py::_build_show_runner_user_prompt`
- `services/script_generation/segment_generator.py`（複数箇所）
- `services/script_generation/metadata_generator.py::_build_prompt`

PR-E ではこの不整合の影響を受けつつ、既存パターンを尊重して「最小限の文字列変更」に留めた。

### 何が問題か
1. **SSOT 違反**: システムプロンプトと同じ重要度を持つユーザープロンプトが、管理方針の異なる場所に分散
2. **プロンプトエンジニアリングの効率低下**: プロンプト調整のたびに Python コード側の修正が必要で、YAML 編集で完結する system prompt と非対称
3. **新エージェント追加時の踏襲リスク**: 新規エージェントも同じパターンで user prompt を Python 埋め込みすると、負債が拡大する

### 推奨対応
`config/prompts.yaml` に `user_prompts` 階層を新設し、各エージェントの user prompt テンプレートを移動。各エージェントは `PromptManager` 経由で template を取得し、変数を `str.format(**kwargs)` で差し込む。

想定される実装範囲:
- `config/prompts.yaml` の階層拡張
- `core/prompt_manager.py` に `get_user_prompt_template(section, key)` 追加
- 5 エージェント（topic_curator / fact_extractor / show_runner / segment_generator / metadata_generator）の `_build_*_prompt` メソッドをテンプレート展開方式に置換
- 既存の動的計算部分（`expected_bridges` 等）は引き続き Python 側で計算、template 変数として渡す

### 前提条件・リスク
- 既存の 125 件テスト全 pass を維持
- プロンプト内容を変えずに配置だけ変更する（挙動回帰ゼロが前提）
- PromptManager のテンプレート変数展開が既存の f-string 機能と等価になることの検証

### 優先度
低〜中。SSOT 思想に反するが実害は顕在化していない。プロンプトエンジニアリングの頻度が高まった場合、または新エージェント追加の頻度が増えた場合に昇格検討。

---

## [BACKLOG] FactExtractor の logger.error 同期（PR-F の横展開）

**記録日**: 2026-04-25
**発見経緯**: PR-F（`review/pr-f-logger-fail-fast-pair`）作業中の「想定外の発見」として判明

### 問題
PR-F で 6 エージェント（topic_curator / show_runner / segment_generator × 3 / metadata_generator）の `finish_reason == "length"` 検知箇所に `logger.error(msg)` を `raise RuntimeError(msg)` の直前に追加し、PR-C の processing_log.txt 収集機構（`_SessionLogFileHandler`）に乗せる対応を行った。

しかし、`services/script_generation/fact_extractor.py:224` の同等な fail-fast 路（PR-A 由来）は **PR-F のスコープ外**として除外していた。理由はタスクスコープが「PR-D の 6 箇所」と明示されていたため。

結果として:
- 7 エージェント中 6 エージェントは `logger.error + RuntimeError` のセット
- FactExtractor のみ `RuntimeError` 単独（logger.error なし）
- **SSOT 思想・運用観察の一貫性の観点で不整合**

### 推奨対応
`fact_extractor.py:224-230` の `if response.finish_reason == "length":` ブロックを、PR-F と同パターンに変更:

```python
if response.finish_reason == "length":
    msg = (
        "FactExtractor output was truncated (finish_reason=length). "
        f"Current max_tokens={self.max_tokens}. "
        "Increase fact_extractor.max_tokens in config.yaml or lower max_facts. "
        "Aborting rather than returning a partial FactSheet."
    )
    logger.error(msg)
    raise RuntimeError(msg)
```

加えて回帰テストを `tests/test_logger_error_on_truncation.py` または既存の `tests/test_fact_extractor.py` に 1 件追加（FactExtractor truncation 時に `logger.error` が呼ばれることを caplog で assert）。

### 想定影響範囲
- 1 ファイル（`services/script_generation/fact_extractor.py`）の数行変更
- テスト 1 件追加
- 破壊的変更なし、API・例外文言・呼び出し側挙動すべて不変

### 優先度
低。PR-F がカバーしなかった残り 1 箇所の SSOT 同期で、運用観察の盲点を完全に埋める。FactExtractor が実運用で truncation を起こす頻度は max_tokens=8192 で低いため緊急性は低いが、揃えると保守時の認知負荷が下がる。

### 工数
XS（30 分以内、機械的な PR-F パターン横展開）
