# 変更履歴

このプロジェクトの全ての重要な変更はこのファイルに記録されます。

フォーマットは [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) に基づいており、
このプロジェクトは [Semantic Versioning](https://semver.org/spec/v2.0.0.html) に準拠しています。

## [Unreleased]

### 修正（2026-04-26: TopicCurator 失敗時のパイプラインクラッシュ修正 / PR-H 緊急修正）
- **問題**（PR-H / `review/pr-h-curation-validation-error-handling`）: PR-B で導入した `CurationResult.topics` 非空 Pydantic validator が、qwen3:8b 等の小型モデルが空 topics を返した際に `ValidationError` を `_parse_curation_response` 内で raise → orchestrator まで未 catch で伝播 → **本運用パイプライン全体がクラッシュ**する致命バグが発生していた
- **PR-B の validator は維持**（壊れた preset_curation を早期検知する設計は正しい）。PR-H では orchestrator 側で `try/except Exception` を Curator 呼び出しにラップし、ValidationError / RuntimeError / その他例外を catch して**フォールバックトピック 1 件で番組生成を完走**させる
- **新メソッド `ScriptOrchestrator._build_fallback_curation_for_failure`**: フォールバック CurationResult 構築ロジックを helper に切り出し、unit test 容易化。例外種別を `error_type` として記録、PR-C/F の logger.error 経路で processing_log.txt に `>>> [ERROR] [services.script_generation.orchestrator] TopicCurator failed; falling back to a single placeholder topic ...` が残る
- **フォールバック topic の構造**:
  - `title="（自動生成失敗:詳細は processing_log.txt 参照）"` — 視聴者から見ても透明
  - `content="TopicCurator がトピック選定に失敗したため、フォールバックトピックで番組を継続しています..."` — 番組内で経緯を説明
  - `priority=1, estimated_turns=10, tone="解説", key_facts=[]`
  - `selection_reason="Curator 失敗時のフォールバック (error_type=...)"` — 下流 SegmentGenerator が読む
  - `curator_reasoning` に元例外の `error_type` と message を埋め込み（後追い debug 用）
- **影響範囲**: `services/script_generation/orchestrator.py` のみ修正（CuratedTopic を import 追加 + try/except + helper メソッド追加）。PR-B の validator・PR-D の fail-fast・PR-E のプロンプト改善・PR-F の logger 連携いずれも完全保持
- **破壊的変更なし**: API 不変。Curator 成功時の挙動は完全に変わらない（try ブロック内で従来通り `curate_topics` を呼ぶ）。失敗時のみフェイルオープンが発動
- **テスト**: `tests/test_orchestrator_curator_fallback.py` 新規、9 件追加（PR-B validator 前提確認 / 例外種別 3 種 (ValidationError/RuntimeError/ValueError) のフォールバック / fallback topic の最小妥当性 / 失敗が viewer に透明 / curator_reasoning に error info / JSON round-trip / 静的構造回帰）

### 追加（2026-04-25: FactExtractor 自己矛盾検出 + プロンプト整合性制約 / PR-G）
- **問題**（PR-G / `review/pr-g-self-inconsistency-detection`）: PR-E のプロンプト改善後も、本運用セッション `output/20260424_220840` で qwen3:8b が **「`extractor_reasoning` に『数値系ファクト 5 件を抽出』と書きながら `facts: []` を返す」自己矛盾型出力**を生成。reasoning も theme_summary も内容は正確（"95% 精度 / 26B vs 27B" 等を正しく特定）にもかかわらず、構造化配列の各要素を埋めるタスクを完遂できない症状で、PR-E のプロンプト圧力強化では未解決
- **案 A: パーサ層での自己矛盾検出 + RuntimeError エスカレーション**
  - `services/script_generation/fact_extractor.py::_parse_fact_sheet_response` の `return` 直前に検出ロジックを追加
  - 正規表現 `_REASONING_COUNT_PATTERN = re.compile(r"\d+\s*[件個つ]")` で reasoning 内の件数言及（"5 件" / "3 個" / "5 つ" 等、半角・全角スペース許容）を検知
  - 「`facts=[]` かつ件数言及あり」を**自己矛盾**として `RuntimeError` 送出 + `logger.error`（PR-F パターン踏襲、PR-C の `processing_log.txt` 収集に乗せる）
  - 偽陽性回避: reasoning が空 / 件数言及なし / `facts` が 1 件以上ある場合は通常 return
  - `orchestrator` の `try/except Exception` が catch して `fact_sheet=None` でフォールスルー（後続処理は破綻しない）
- **案 B: prompts.yaml への整合性制約追加**
  - `config/prompts.yaml::orchestrator.fact_extractor` の禁止事項セクションに「`extractor_reasoning` に『N 件抽出した』と書きながら facts 配列を空のまま返すこと」を追加
  - 「reasoning に書いた件数と facts 配列の長さは**必ず一致**させる」と明示
  - 「PR-G で本パーサ層に検出ロジックが入っており、矛盾は RuntimeError として検知される」と LLM に通知（守らないと拒否される旨を明示）
- **次回本運用での効果確認**: PR-C/F の logger 収集により `>>> [ERROR] [services.script_generation.fact_extractor] FactExtractor self-inconsistency detected: ...` が `processing_log.txt` に残る。BACKLOG #3 の「PR-E 効果観察」と並行して本症状の発生頻度を測定可能
- **長期対策（BACKLOG 既存）**: 案 A/B はあくまで症状の検知と LLM への明示圧力。根治は **Ollama Structured Output**（BACKLOG #4）または **モデル変更**（BACKLOG #5）に委ねる
- **破壊的変更なし**: API 不変、`facts` が 1 件以上ある正常系の挙動・既存パーサの skip ロジック・PR-D の fail-fast 設計すべて完全保持
- **テスト**: `tests/test_fact_extractor_self_inconsistency.py` 新規、13 件追加（陽性ケース 7: 様々な件数表現パターン / 陰性ケース 4: 偽陽性回避 / プロンプト回帰 1 / 統合 1）

### 修正（2026-04-25: PR-C / PR-D 連携漏れの解消、`logger.error` 併用で processing_log.txt 収集を回復）
- **問題**（Issue B-PR-F / PR-F / `review/pr-f-logger-fail-fast-pair`）: PR-D で 6 エージェントの `finish_reason=length` 時の挙動を「`logger.warning` 削除 + `RuntimeError` raise のみ」に変更した結果、PR-C の `processing_log.txt` 収集機構（root logger に attach した `_SessionLogFileHandler`）が捕捉対象を失っていた。本運用セッション `output/20260424_220840` で MetadataGenerator truncation が発生したが、processing_log.txt には rich console 経由の `⚠` 行のみが残り、`>>> [ERROR]` プレフィックス付きの logger 行が **0 件**だった
- **PR-D の fail-fast 設計は完全保持**しつつ、6 箇所の `finish_reason == "length"` 検知に `logger.error(msg)` を `raise RuntimeError(msg)` の直前に追加（同一の `msg` 変数を両者で参照、SSOT 維持）
  - `services/script_generation/topic_curator.py`
  - `services/script_generation/show_runner.py`
  - `services/script_generation/segment_generator.py`（1-phase JSON / Phase 1 creative / Phase 2 JSON の 3 箇所）
  - `services/script_generation/metadata_generator.py`
- **scripting_phase.py 上位 catch にも logger.error 併用を追加**: MetadataGenerator catch / Visual identity catch で `logger.error(..., exc_info=True)` を `cb.log` の併用ログとして発火。スタックトレースが processing_log.txt に残るため、本運用での原因究明が大幅に容易に
  - `services/pipeline/scripting_phase.py` 先頭に `import logging` + module-level `logger` 追加
- **対象外（スコープ判断）**:
  - `fact_extractor.py` の同パターン（PR-A 由来）: タスクスコープが「PR-D の 6 箇所」と明示されていたため対象外。整合性観点で別 PR で同期する価値あり（BACKLOG 候補）
  - `ollama_client.py:162` の旧式 `logger.warning("max_tokens limit reached...")`: 古い実装で fail-fast 化されておらず、現行フローでは ollama_adapter が利用されているため対象外
- **破壊的変更なし**: API 不変、RuntimeError raise の挙動・例外文言・呼び出し側 try/except のフォールバックすべて完全保持
- **テスト**: `tests/test_logger_error_on_truncation.py` 新規、7 件追加（6 エージェント × `logger.error` 発火 + 1 件で「logger.error と RuntimeError の文言が完全一致すること」を SSOT として保証）

### 修正（2026-04-25: MetadataGenerator.max_tokens を 2048 → 4096 に引き上げ）
- **本運用セッション `output/20260424_220840` で `finish_reason=length` による truncation が発生**し、メタデータ生成がデフォルト値フォールバックに落ちた実績を受けた運用チューニング
- `core/models/config.py::MetadataGeneratorConfig.max_tokens` の Pydantic default と `config.yaml::orchestrator.metadata_generator.max_tokens` を**両方 4096 に揃えて SSOT 維持**
- 出力想定: title/thumbnail_title/description/hashtags 合計 ~580 文字 × 日本語トークン化率 ~2.5 = 実使用 ~1500 トークン + JSON オーバーヘッド。4096 は 2x 余裕を持たせた運用値
- 破壊的変更なし（上限値のみ変更、API/データ形式不変）。既存 125 件テスト全 pass

### 追加（2026-04-24: プロンプト明示圧力強化でフィールド省略対策）
- **TopicCurator と FactExtractor のプロンプトを改善**（Issue B / PR-E / `review/issue-B-prompt-pressure`）
  - 本運用で発見された共通病理「小型モデル（qwen3:8b）がプロンプトで明示されていないフィールドを省略する」への対処
  - **TopicCurator 改善** (A+B+C 手法適用):
    - `title` フィールドに必須化・20〜40文字・数値か固有名詞を最低1つ含む制約を明示
    - 悪い例（"デンマークの研究" のような短い国名+研究種別）と良い例（"デンマーク研究で70%が関節痛軽減"）を両方掲載
    - 既存の title 欠落時フォールバック（`topic_curator.py:239-257` の合成ロジック）は保持。今回の改善で発動頻度が下がる想定
    - `config/prompts.yaml::orchestrator.curation` に選定ルールと禁止事項を追記
    - `services/script_generation/topic_curator.py::_build_curation_user_prompt` の JSON 例示プレースホルダ を "トピックタイトル" から制約記述に変更
  - **FactExtractor 改善** (A+B+E 手法適用):
    - `facts` を最低 5 件抽出する指示を追加（空配列禁止）
    - 意外性スコア 4〜6（「一般人にとって新情報」）を積極的に含めるハードル緩和指示
    - ユーザープロンプトの例示を英語圏 AI 文脈（"1200万円"/"OpenAI"）→ 日本語医療系（"亜麻仁油"/"デンマーク"/"70%"）に差し替え
    - `extractor_reasoning` 空文字禁止（80〜150 文字必須）指示を追加
    - `config/prompts.yaml::orchestrator.fact_extractor` + `services/script_generation/fact_extractor.py::_build_fact_extractor_user_prompt` で対応
  - **スコープ外（BACKLOG.md に記録）**:
    - Ollama Structured Output（`format` パラメータでの JSON schema 強制）: プロンプト改善で効果不十分な場合の次の一手
    - モデル変更（qwen3:8b → 中型）: 上記いずれも効果不十分だった場合の最終手段
    - 実運用効果観察: 1 日 1 回の本運用セッションで PR-C の logger 収集経由で追跡
- **破壊的変更なし**: 既存の JSON 出力フォーマット契約（フィールド名・型・構造）は不変。プロンプト文言が改善されただけ
- **テスト**: `tests/test_prompt_pressure.py` 新規、10 件追加（プロンプトから明示圧力の重要キーワードが将来リグレッションで消えないことを回帰的に保証）

### 追加（2026-04-24: max_tokens config 駆動化の横展開 / 全エージェント統一 fail-fast）
- **LLM を呼ぶ 5 エージェント 6 箇所の `max_tokens` を config 駆動化**（Issue C / PR-D / `review/issue-C-max-tokens-unification`）
  - PR-A で FactExtractor に採用した「`max_tokens` は config 駆動、`finish_reason==length` なら `RuntimeError` を送出」パターンを横展開
  - 対象: `TopicCurator` / `ShowRunner` / `SegmentGenerator` (3 箇所: 1-phase JSON / Phase 1 creative / Phase 2 JSON) / `MetadataGenerator`
  - 既定値は各エージェントの**旧ハードコード値をそのまま踏襲**（数値の引き上げは運用判断として `config.yaml` で変更）
    - `topic_curator.max_tokens = 8192`
    - `show_runner.max_tokens = 4096`
    - `segment_generator.max_tokens_single = 8192`
    - `segment_generator.max_tokens_phase1 = 4096`
    - `segment_generator.max_tokens_phase2 = 2048`
    - `metadata_generator.max_tokens = 2048`
  - **`finish_reason==length` 時の挙動統一**: 全 6 箇所で `RuntimeError` を送出し、呼び出し側（`orchestrator` / `scripting_phase` の `try/except`）がフォールバック処理でハンドリング
    - 本運用で発生した MetadataGenerator の truncation は、従来 `logger.warning` + 部分 JSON parse 試行で silent に対処されていたが、PR-D では fail-fast 化により早期検知・デフォルトメタデータへのフォールバックが明示的になる
    - SegmentGenerator Phase 1（creative markdown）は従来 `finish_reason` チェックすら存在せず、truncated markdown が Phase 2 JSON 変換に渡って parse 失敗していた問題も同時解消
- **`core/models/config.py` に Config クラス新設**: `TopicCuratorConfig` / `SegmentGeneratorConfig` / `MetadataGeneratorConfig`。`ShowRunnerConfig` には `max_tokens` フィールド追加
- **`config.yaml`**: `orchestrator.{topic_curator, show_runner, segment_generator, metadata_generator}.max_tokens*` を追加（旧ハードコード値と同値）
- **破壊的変更なし**: API シグネチャ不変、既定値は旧ハードコードと同値のため既存セッションに影響なし。finish_reason==length 時の挙動変化（warning → RuntimeError）は発動条件が truncation 発生時のみで、かつ呼び出し側 `try/except` で既にフォールバック処理済み
- **テスト**: `tests/test_max_tokens_unification.py` 新規、12 件追加（各エージェント × (config 伝播 / length 時 RuntimeError) の 2 軸 × 6 箇所）

### 追加（2026-04-24: Python logger 出力の processing_log.txt への統合 / 運用観測性の向上）
- **`workflow.py::LogFileWriter` に FileHandler ライフサイクルを追加**（Issue A / PR-C / `review/issue-A-logger-capture`）
  - セッション開始時に root logger へ `FileHandler(processing_log.txt, level=WARNING)` をアタッチし、`finalize()` でデタッチ
  - 従来 stderr にしか出ていなかった `logger.warning/error` 系が `processing_log.txt` に自動記録されるように（具体例: FactExtractor の "Unknown category" 警告、TopicCurator の title 欠落警告、MetadataGenerator の truncation 警告、Ollama adapter の空レスポンス例外メッセージ等）
  - 既存の `.write(msg)` 呼び出し・rich markup 出力は挙動不変（純追加、破壊的変更なし）
  - Formatter: `>>> [%(levelname)s] [%(name)s] %(message)s` — 既存の `[cyan]...` 等の rich markup 行と視覚的に区別
  - ログレベルは **WARNING 固定**（DEBUG/INFO は意図的に除外、ノイズ抑止）。config 駆動化は将来 PR で検討
- **残留ハンドラ汚染防止**: 専用サブクラス `_SessionLogFileHandler` を定義し、`LogFileWriter.__init__` で `isinstance` ベースで前回 session の残留ハンドラのみを安全に掃除（他目的の `logging.FileHandler` には干渉しない）。Gradio 長命プロセスで `finalize()` 漏れが起きた場合の「新 session の warning が前回ファイルへ書き込まれる」汚染バグを防止
- **テスト**: `tests/test_logger_capture.py` 新規、9 件追加（basic capture / ERROR 捕捉 / INFO 非捕捉 / finalize 後隔離 / 複数 session 非汚染 / `.write()` 後方互換 / logger と `.write()` 共存 / 残留ハンドラ掃除 / 非 `_SessionLogFileHandler` の誤検知ゼロ）

### 破壊的変更（2026-04-23: CurationResult.topics 非空契約の強制）
- **`core.models.curation.CurationResult.topics` を非空必須に**（Phase 4 review #4 / `review/phase4-fact-extractor-b`）
  - Pydantic `@field_validator` で `len(topics) == 0` の場合 `ValidationError` を送出
  - 旧実装では Orchestrator 層で `preset_curation is not None and preset_curation.topics` と暗黙に非空を前提としていたが、条件違反時は silent に Curator 実行へフォールスルーしていたため、壊れた preset が検知されず debug を困難にしていた
  - **影響**: 既存セッションの `curation_result.json` で `topics: []` の壊れたデータがあれば、load 時（`SessionManager.load_curation_result`）に ValidationError が出る
  - **移行手順**: 該当セッションは (a) 当該 JSON を手動で修復、(b) `curation_result.json` を削除して再実行、のいずれかで対応。通常の利用では CurationResult が空であること自体が異常系のため影響を受けない想定

### 追加（2026-04-23: ExtractedFact.category の型固定 / SSOT 双方向参照）
- **`core.models.fact_sheet.FactCategory` リテラル型新設**（Phase 4 review #8）
  - `FactCategory = Literal["数値", "人物", "事件", "比較", "引用", "その他"]`
  - `ExtractedFact.category` を `str` から `FactCategory` に型固定、既定値を `"general"` → `"その他"` に統一（プロンプト指示との言語整合）
  - `fact_extractor.py::_parse_fact_sheet_response` のフォールバック処理を「未知値は `logger.warning` を出しつつ `"その他"` に正規化」に置換。旧 `str(f.get("category", "general") or "general").strip() or "general"` は撤去
  - SSOT の所在を `FactCategory` docstring と `config/prompts.yaml` の両方に明記し、双方向参照コメントを挿入（片方だけ変更すると LLM 出力がフォールバック層に全件落ちる旨を明文化）
  - `typing.get_args(FactCategory)` で runtime 集合を派生させ、Literal 定義を唯一の情報源に統一

### リファクタリング（2026-04-23: 台本生成の単一情報源化 / SSOT）
- **`workflow.py::execute_scripting_phase` 削除 → `_execute_gradio_scripting_phase` へ改名**: Gradio 自動モードの台本生成フェーズと HITL/CLI 向けの `services.pipeline.execute_scripting_phase` で挙動が乖離していた問題を解消
  - リサーチステップだけを Gradio 層（`workflow.py`）に残し、台本生成ロジックは `services.pipeline.execute_scripting_phase` に完全委譲
  - 結果として **全モード（Gradio 自動 / HITL / CLI main.py）で ShowRunner・MetadataGenerator・VisualIdentity・show_plan.json 永続化 などが同一挙動で動作**
  - `ResearchResult → ResearchBrief` 変換と `RadioScriptArtifact → ScriptingPhaseResult` 変換のブリッジ層を新設（`dataclass` / `pydantic` 両対応）
  - 2-Story Mode（第1部＋第2部）でも動作。Part2 では `preloaded_research_data` 経路から `ResearchBrief` を合成して保存
  - 旧 workflow.py 版のセグメント生成・speaker diagnostics・visual identity 実装を削除（pipeline 版が完全上位互換）
- **`SessionManager` に `session_dir` 明示指定オプションを追加**: 既定の `workspace/{session_id}/` 規約を上書きし、Gradio 自動モードの `output/{timestamp}/` に直接マウント可能に。既存の呼び出しは完全後方互換
- **回帰テスト追加**: `tests/test_show_runner.py` に `session_dir` オーバーライド動作 2 件を追加（全 51 件 pass）

### 追加（2026-04-23: ShowRunner - 番組構成プランナーエージェント）
- **新エージェント `ShowRunner`** — Curator 選定後に番組全体の物語構造を設計する階層の追加
  - 設計 5 軸: 全体アーク / 導入フック戦略 / トピック間ブリッジ / 締め戦略 / トーン配分
  - `services/script_generation/show_runner.py`, `core/models/show_plan.py` 新規追加
  - `ScriptOrchestrator` に Step 1.5 として統合。`SegmentGenerator` の `generate_intro/deep_dive/conclusion` に `show_plan_hint` 引数を追加し、設計意図を各セグメント生成プロンプトに defensively 差し込む
  - セッションへ自動永続化 (`workspace/{session_id}/show_plan.json`)。`SessionManager.save_show_plan/load_show_plan/has_show_plan` を追加。再実行時は自動ロード
  - HITL Gate 2b 対応基盤: `execute_scripting_phase(preset_show_plan=...)` でユーザー編集済み ShowPlan を受け取れる
  - 設定: `config.yaml > orchestrator.show_runner.enabled` で ON/OFF。Pydantic モデル既定は `false`（後方互換）、同梱の `config.yaml` では `true` で有効化済み
  - 失敗時フォールバック: ShowRunner の LLM 呼び出しが失敗しても警告ログのみで従来フローを継続
  - プロンプト: `config/prompts.yaml > orchestrator.show_runner` 新設
  - テスト: `tests/test_show_runner.py` に 10 件追加（データモデル往復 / JSON パース耐性 / プロンプト差し込み / 後方互換 / SessionManager 往復）

### 修正（2026-04-23）
- **`services/script_generation/topic_curator.py` ローカル LLM 対策**: `qwen3:8b` 等が稀に `title` フィールドを省略する症状に対し、`key_facts[0]` → `selection_reason` → プレースホルダの順でタイトルを合成するフォールバックを追加。ShowRunner が空タイトルで動作不能にならないよう防御的に対応
- **`app_hitl_handlers.py::_show_curation_editor` DataFrame truthiness バグ**: `if topics_df:` が pandas.DataFrame で `ValueError: The truth value of a DataFrame is ambiguous` を吐いていた箇所を、`len(topics_df) > 0` による明示的な空判定に修正
- **`services/pipeline/scripting_phase.py` 実在しない API 呼び出しの除去**: `execute_curation_only` / メタデータ生成部が `ExecutionContext.create_llm_port()`（未実装メソッド）を呼んでいた箇所を `LLMAdapterFactory.create()` に統一（`ScriptOrchestrator` と同じパターン）

### 修正（2026-04-18: コードレビュー対応・耐障害性とSSOT強化）
- **`services/script_generation/gemini_client.py` フォールバック分割ロジックの堅牢化**
  - `script.sections` が空のとき `ValueError` を送出して早期リターン（無意味な分割処理を防止）
  - `segment_size` を `max(10, total // 3)` から `max(1, math.ceil(total / 3))` に変更し、短いスクリプトでも適切に3分割されるよう改善
  - セグメント種別割当をチャンクインデックス基準に変更：`idx == 0` → intro / `idx == num_chunks - 1 and num_chunks > 1` → conclusion / それ以外 → `deep_dive_{idx}`
  - 単一チャンクのみ生成される場合は `intro` として扱い、`conclusion` との重複ラベル付与を排除
- **`services/comparison_report.py` SSOT違反（JPY換算ハードコード）の修正**
  - `cost_jpy = cost_usd * 150.0` を `calculator.usd_to_jpy`（`config.yaml` 由来）に置き換え
  - `comparison_session.py` との実装整合性を確保
- **`services/cost_calculator.py` サイレントフォールバックの可視化**
  - 未登録モデル名が渡された場合、`logger.warning` でプロバイダ名・モデル名・適用された代替単価を明示出力
  - 価格表自体が空のケースでも警告を出力
  - `_check_free_tier` の判定条件を `request_count <= 1` から `1 <= request_count <= 1` に変更し、`request_count == 0`（Gemini未使用）のケースを Free Tier 扱いから除外
- **`services/audio_synthesis/voicevox_client.py` チャプター名フォールバック補完**
  - `_get_chapter_title` の `section_titles` マッピングに `deep_dive_1/2/3`、`conclusion` を追加
  - `config/prompts.yaml` の新しいセクション命名規約（`deep_dive_N` / `conclusion`）と整合

### 追加
- **HITLモード（Human-in-the-Loop）**: ユーザーが各フェーズで介入・編集できる新しいワークフローモード
  - リサーチ結果のプレビューと承認機能
  - 台本のリアルタイム編集機能（テキストエディタ/JSONエディタ）
  - 既存データのインポート機能（research_brief.json / script.json）
  - 3つのGate（Research → Script → Production）による段階的な制作フロー
  - `app_hitl.py` と `app_hitl_handlers.py` を新規作成

### 修正
- **HITLモードのUX改善**: Human-in-the-Loopの思想に沿った明示的なユーザー介入を実現
  - リサーチ承認後の自動台本生成を廃止（`.then()`チェーンを削除）
  - 各フェーズの実行はユーザーが明示的にボタンをクリックした時のみ開始
  - 意図しないAPI呼び出しとコスト発生を防止
  - `app.py` のイベントハンドラを変更

- **セキュアなエラーハンドリング**: 本番環境でのセキュリティリスクを排除
  - UIに表示するエラーメッセージを簡潔化（`str(e)`のみ）
  - 詳細なスタックトレースは`logger.error()`でサーバーログにのみ記録
  - 全8箇所のエラーハンドリングを見直し（research/script/production各フェーズ）
  - 機密情報（ファイルパス、環境変数等）の露出を防止
  - `app_hitl_handlers.py` を変更

### リファクタリング
- **コード品質の改善**: Pythonベストプラクティスへの準拠とデッドコードの削除
  - `import json`をファイル冒頭に移動（PEP 8準拠）
  - 過剰なデバッグログを削除（`logger.debug()`の整理）
  - 空レスポンス時のエラーメッセージを具体化（"Visual identity API returned empty response. Check API key and model availability."）
  - 未使用の`hitl_script_artifact_state`変数を削除
  - `services/script_generation/visual_palette_generator.py` と `app_hitl.py` を変更

- **Git管理の適正化**: テスト実行結果の混入を防止
  - `.gitignore`に`workspace/`ディレクトリを追加
  - セッション単位のワークスペースファイルをバージョン管理から除外

### 追加
- **パイプライン分離アーキテクチャ（Pipeline Decoupling Architecture）**: モノリシックな動画生成パイプラインを「リサーチ」「台本作成」「動画生成」の3つの独立したフェーズに分離
  - **中間成果物のデータモデル**:
    - `ResearchBrief`: リサーチフェーズの出力成果物（検索クエリ、リサーチ内容、キュレーション結果を含む）
    - `RadioScriptArtifact`: 台本作成フェーズの出力成果物（台本、セグメント情報、ビジュアルアイデンティティを含む）
    - `core/models/artifacts.py` を新規作成
    - `core/models/script.py` に `RadioScriptArtifact` を追加
  - **セッション管理システム**:
    - `SessionManager`: `workspace/{session_id}/` 配下でのファイルI/Oを管理
    - 各フェーズの中間成果物を永続化し、フェーズ単位での実行・再開を可能に
    - `core/session_manager.py` を新規作成
  - **フェーズ分離サービス**:
    - `execute_research_phase()`: 企画（検索計画作成）とリサーチ（情報収集）を実行
    - `execute_scripting_phase()`: ResearchBriefから台本を生成
    - `execute_production_phase()`: RadioScriptArtifactから音声合成と動画レンダリングを実行
    - `services/pipeline/` ディレクトリを新規作成
  - **CLI再設計**:
    - `--phase` オプション: `all`（一気通貫）、`research`（リサーチのみ）、`script`（台本作成のみ）、`render`（動画生成のみ）
    - `--session` オプション: 既存セッションIDを指定して続きから実行
    - `--research-brief` / `--script` オプション: 外部ファイルから読み込んで実行
    - `main.py` に引数パース機能を追加
  - **期待効果**:
    - フェーズ単位でのデバッグ・テストが可能に
    - 失敗したフェーズのみを再実行可能（コスト削減）
    - 各フェーズを独立して改善・置き換え可能（拡張性向上）
    - 将来的なエージェンティックAI導入の基盤を構築
  - **後方互換性**: 既存の一気通貫モード（`--phase all`）も維持

- **Subject-Driven画像生成アーキテクチャ（パラダイムシフト）**: FLUX.1画像プロンプト生成を「Style偏重」から「Subject最優先」へ抜本的に再設計
  - **Context Hydration（文脈の十分な供給）**:
    - `_build_segment_context()` を全面リファクタリング
    - 台本情報の切り詰めを大幅に緩和（3ターン/200文字 → 10-16ターン/800文字）
    - セグメント長に応じた適応的サンプリング戦略を導入
    - 文末での自然な切断処理を実装
  - **Subject-First Prompt Architecture（主題最優先の指示体系）**:
    - `SYSTEM_PROMPT_TEMPLATE` を完全再構築
    - PRIMARY FOCUSセクションを新設し、具体的な被写体抽出を最優先指示に
    - 例文を抽象的な空間描写から具体的な被写体中心の描写へ全面刷新
    - 「画風を守れ」と「被写体を描け」の優先度を逆転（被写体 > 画風）
  - **Narrative-Visual Alignment（物語と視覚の連携）**:
    - セグメントタイプ別の構成ガイダンスを映像ディレクター視点の具体的指示に昇華
    - 抽象的な「雰囲気」指定から、具体的な「どの被写体にカメラを向けるか」への転換
    - intro/deep_dive/conclusionごとに、フレーミング・被写体選択・視覚的ディテールを明示
  - **サムネイル生成の同時改善**:
    - `THUMBNAIL_SYSTEM_PROMPT_TEMPLATE` も同様にSubject-Driven設計へ移行
    - クリック率最適化のため、ONE HERO SUBJECTの原則を強調
  - `services/script_generation/image_prompt_generator.py` を変更
  - 構文チェック完了、既存データフローとの互換性確認済み
  - **期待効果**: テーマとの関連性が劇的に向上し、視聴者が「何の動画か」を一目で理解できる画像生成を実現
  - **コードレビュー後の品質改善**:
    - ターン抽出時のリスト重複バグを修正（長尺セグメントで中間・末尾ターンが最初の12ターンと重複していた問題）
    - テキスト切断ロジックを堅牢化（句点が見つからない場合の処理を明確化）
    - サムネイルプロンプトの指示を統一（SYMBOLIC → CONCRETE, SUBJECT-DRIVENに変更し、LLMの混乱を防止）

- **AI生成画像の謎文字（Gibberish Text）抑制強化**: FLUX.1画像生成時に意図しない文字やロゴが混入する問題を徹底的に防止
  - **FLUX APIのネガティブプロンプト強化**: `"no text"` から `"text, gibberish, fake text, distorted letters, writing, watermark, signature, logo, words, characters, alphabet"` へ拡張
  - **LLMプロンプト制約の強化**: `SYSTEM_PROMPT_TEMPLATE` と `THUMBNAIL_SYSTEM_PROMPT_TEMPLATE` の制約を `"no text, no writing, no watermarks"` に強化
  - **フォールバック処理の統一**: `_enforce_quality_keywords()` でも同様の制約を適用
  - `services/media_processing/flux_client.py` と `services/script_generation/image_prompt_generator.py` を変更
  - **期待効果**: 画像の視覚的クリーンさが向上し、プロフェッショナルな仕上がりを実現

- **ジングル前ポーズ機能**: セグメント境界でジングル再生前に自然な一拍（間）を挿入
  - `config.yaml` に `pre_jingle_pause_sec` 設定を追加（デフォルト: 0.5秒）
  - `VoicevoxClient` でジングル前ポーズを音声トラックに挿入
  - `TimelineCalculator` でジングル開始タイミングとビデオ切り替えタイミングを調整
  - ジングル再生がより自然で聴きやすくなり、リスナー体験が向上

### 修正
- **ジングル選択の不具合修正**: サブフォルダ内の素材ファイルが誤って選択される問題を修正
  - `JingleProvider` がルート直下のファイルのみをスキャンするように変更
  - `アーカイブ/` や `素材/` フォルダ内の未完成ファイルを除外
  - 意図しない音声ミックス（個別の声のジングルが選ばれる問題）を防止
  - `services/media_processing/jingle_provider.py` を変更
- **BGMダッキングの堅牢性向上**: ジングル再生中のBGM抑制機能における重大なバグを修正
  - **ゼロ除算の防止**: BGM音量がゼロまたは負の値の場合のランタイムクラッシュを防ぐガードを追加
  - **音量逆転バグの修正**: ジングル再生中にBGM音量が増加するのを防ぐため、ダッキングレベルの検証を修正
  - **設定アクセスの最適化**: 繰り返しの `getattr` 呼び出しの代わりに、`__init__` でダッキング設定をキャッシュするようリファクタリング
  - **ジングル尺ゼロの安全性**: 破損した音声ファイルによる不正なビデオタイミングを防ぐ検証を追加
  - `services/video_rendering/audio_track_renderer.py` と `timeline_calculator.py` を変更
  - 全ての変更を `python -m py_compile` で構文チェック済み

- **動画切断問題の修正**: ポストロールがセグメントタイミング計算に含まれていないため、動画が5秒早く終了する問題を修正
  - `services/audio_synthesis/voicevox_segment_timing.py` を変更し、最後のセグメントにポストロール時間（5秒）を追加
  - 動画の長さが音声の長さと完全に一致するように修正（例: 497.6秒の音声 → 478.1秒ではなく497.6秒の動画）
  - 動画の最後で音声が突然切れる問題を解決
  
- **FLUX.1タイムアウト問題の修正**: 低VRAM環境向けにFLUX.1画像生成設定を最適化
  - GPU性能低下に対応するため、タイムアウトを120秒から300秒に延長
  - 推論ステップ数を20から10に削減（FLUX.1 schnellは4〜10ステップで良好な性能を発揮）
  - 解像度を1344×768から1024×576に低減（VRAM使用量50%削減、16:9アスペクト比を維持）
  - 処理時間の改善見込み: 211秒 → 50〜60秒/画像
  - `config.yaml` のFLUX設定を最適化の詳細説明付きで変更
  
- **動的モードフォールバック失敗の修正**: 動的モード時にImageProviderが静的画像をスキャンしない問題を修正
  - `services/media_processing/image_provider.py` を変更し、モードに関わらず常に静的画像をスキャンするように修正
  - FLUX.1生成が失敗またはタイムアウトした場合の静的画像への自動フォールバックを有効化
  - フォールバック時の「背景画像が見つかりません」エラーを防止

### リファクタリング
- **ビジュアルパレットアーキテクチャのクリーンアップ**: ビジュアルアイデンティティシステムのコード品質と保守性を改善
  - 重大な型アノテーションバグを修正（`Any` のインポート不足、`any` → `Any` の修正）
  - 適切な非同期コンテキストのため、パレット生成をPhase 2.5から `execute_scripting_phase` 内に移動
  - データの不変性を維持するため、`ScriptingPhaseResult` の事後変更を排除
  - 重複するフォールバックカラー文字列を `DEFAULT_COLOR_PALETTE` クラス定数に抽出（DRY原則）
  - 実際の動作を正確に反映するようエラーメッセージを更新（コンポーネントデフォルトへのフォールバック）
  - 全ての変更を `python -m py_compile` で構文チェック済み

## [3.5.0] - 2026-02-15

### 追加
- 長尺台本生成のための階層的エージェントワークフロー
- 多次元スコアリングによるトピックキュレーション
- セグメントベース生成（intro/deep_dive/conclusion）
- セグメント間のコンテキスト継続性

## [3.4.0] - 2026-01-XX

### 追加
- マルチLLMプロバイダーサポート（Gemini/OpenAI/Anthropic）
- プロバイダー選択のためのファクトリーパターン
- OpenAI Structured Outputs統合
- Anthropic Tool Calling統合

## [3.3.2] - 2025-12-XX

### 追加
- 2部構成エピソードモード
- APIヘルスチェック機能
- 話者入れ替わりの自動検出と修正
- API失敗時のリトライロジック

## [3.3.1] - 2025-12-XX

### 追加
- Perplexity API呼び出しハードリミット
- セッションベースのリサーチ結果キャッシュ

## [3.3.0] - 2025-11-XX

### 追加
- ネガティブプロンプト（回避トピック）機能
- ラウドネス正規化（-14 LUFS）
- Gradioによるビジュアル進捗バー
- 開発用モックモード
- NVENC GPU高速化

## [3.2.0] - 2025-10-XX

### 追加
- コア機能を含む初回リリース
- Perplexityリサーチ統合
- Gemini台本生成
- VOICEVOX音声合成
- FFmpeg動画レンダリング
- サムネイル生成
