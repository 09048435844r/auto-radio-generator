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
