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
