# Step 4 v2 実装プラン: Gemini 台本生成経路の物理削除

**版数:** 1.1（実装中に依存関係調査で revised）
**作成日:** 2026-05-10
**対象リポジトリ:** auto-radio-generator (Windows / E:\windsurf\auto_radio_generator)
**派生元ブランチ:** fix-json (Step 3 マージ済み HEAD = `9c752fb`)
**作業ブランチ:** `feature/v2-remove-gemini-script-path`
**フェーズ:** 実装中

## 改訂ノート (v1.1)

実装着手後、以下の依存関係が判明したためプランを Yuru-Stoic 方向に縮退:

1. **HITL が `services/pipeline/scripting_phase.py` を使用** (`app_hitl_handlers.py:21,22,303,775,1191`)
   → scripting_phase.py 削除を撤回。@deprecated 注記のみに留める。
2. **`services/pipeline/research_phase.py` が `GeminiClient.create_research_plan` を必須呼び出し** (line 56-57)
   → Perplexity ベンチマーク経路は事前の AI 検索計画が必要。research_phase.py を改修して
      planning step を skip し、`queries=[theme]` の単純化フォールバックに切り替える。
3. **`scripting_phase.py` が `services/script_generation/visual_palette_generator.py` を使う**
   (dynamic background mode、line 468)
   → visual_palette_generator.py 削除を撤回。
4. **`services/media_processing/image_provider.py` + `thumbnail_background_generator.py` が
   `services/script_generation/image_prompt_generator.py` を使う**
   → image_prompt_generator.py 削除を撤回。
5. **`AnthropicClient` / `OllamaClient` / `OpenAIClient` が `IScriptGenerator` を実装**
   → IScriptGenerator 削除を撤回。
6. **`workflow.create_script_generator` を scripting_phase.py が import**
   → 関数自体は保持。"gemini" ブランチのみ削除。

→ 結論: 物理削除対象は最終的に **gemini_client.py + adapters/gemini_adapter.py + GeminiUsage alias** のみ。
それ以外は **gemini ブランチ削除 + @deprecated 注記** で対応する Yuru-Stoic 縮退案。

---

## Context

Step 3 で `@deprecated` 警告付きで残置した旧 LLM 経路のうち、**Gemini 台本生成経路のみを物理削除する**。Perplexity リサーチ経路（ベンチマーク用途）と Step 3 で導入した外部台本モードは完全保持する。本作業の目的は:

- 旧 Gemini 台本生成のコードパスを取り除き、依存ファイル数を削減してメンテナンス負荷を下げる
- Perplexity リサーチ経路を保持することでベンチマーク機能を維持
- 外部台本モード（Mac 側 radio_director の VerifiedScript JSON 受け取り）を **唯一の台本生成経路** に確定

設計原則: **Yuru-Stoic** — 削除しきれないものは無理に削除せず、`@deprecated` 残置で許容。

---

## Part A: 環境調査結果

### A.1 ResearchSource の依存関係マトリクス（最重要、削除安全性の根拠）

| ファイル | 行 | 用途 | 分類 | 削除影響 |
|---|---|---|---|---|
| `core/interfaces/researcher.py` | 7 | `ResearchResult.sources` の型注釈 | 共通 | 保持必須 |
| `core/models/research.py` | 9 | `ResearchSource` 定義本体 | 共通 | 保持必須 |
| `services/research/perplexity_client.py` | 19 | Perplexity 結果から ResearchSource 生成 | Perplexity | 保持必須 |
| `services/publishing/metadata_builder.py` | 8 | 参考文献 ReferenceEntry 型注釈 | 共通 (Publishing) | 保持必須 |
| `workflow.py` | 40 | `ReferenceEntry = str \| ResearchSource` 型注釈 | 共通 | 保持必須 |
| `workflow.py` | 1876–1891 | 研究 import 経路で ResearchBrief.research_sources → ResearchResult.sources 変換 | Perplexity + 外部台本対応 | 保持必須 |
| `services/pipeline/scripting_phase.py` | 72 | `execute_fact_extraction_only` 内で `ResearchSource.model_validate` | **Gemini 台本生成専用** | **削除可** |
| `services/pipeline/scripting_phase.py` | 161 | `execute_curation_only` 内で `ResearchSource.model_validate` | **Gemini 台本生成専用** | **削除可** |
| `services/pipeline/scripting_phase.py` | 280 | `execute_scripting_phase` 内で `ResearchSource.model_validate` | **Gemini 台本生成専用** | **削除可** |

→ **`ResearchSource` の保持判断**: モデル本体 + Perplexity 経路 + Publishing 共通利用がすべて存続するため、**そのまま保持**。Step 3 完了時の懸念事項（"publishing が依存しているため移動も削除も禁止"）は引き続き有効。

### A.2 GeminiClient とその関連クラスの使用範囲

| 場所 | 用途 | 削除可否 |
|---|---|---|
| `services/script_generation/gemini_client.py` | Gemini API 直接呼び出しによる台本生成 + 検索計画生成 | **削除対象** (クラス全体) |
| `services/script_generation/adapters/gemini_adapter.py` | provider-agnostic な ILLMPort 経由の Gemini アダプター | **削除対象** |
| `app.py:34, 709, 830` | UI health check + AI プロデューサーモード（旧 Generator タブ handler 内） | **削除対象** |
| `workflow.py:706–723 (create_script_generator)` | provider="gemini" 等の factory ラッパ | **編集** (gemini ブランチ削除、他 provider は保留判断) |
| `workflow.py:784, 1406` | `create_research_plan` 呼び出し（provider="gemini" 固定） | **削除対象** (planning phase ごと) |
| `services/script_generation/llm_factory.py` | provider 別 factory | **編集** ("gemini" ブランチ削除) |
| `services/script_generation/__init__.py` | re-export | **編集** |

### A.3 services/script_generation/ の責務マッピング（最も判断が分かれる領域）

調査の結果、以下のファイルは **provider-agnostic 設計** で、`LLMAdapterFactory` 経由で Ollama / OpenAI / Anthropic でも動作するが、現状の運用では **Gemini 経路でしか実際には呼ばれていない**:

| ファイル | 直接 Gemini 依存 | 外部台本モードで使用 | Perplexity 経路で使用 | 推奨判断 |
|---|---|---|---|---|
| `gemini_client.py` | ◎ (Gemini API 直叩き) | ❌ | ❌ | **削除** |
| `adapters/gemini_adapter.py` | ◎ | ❌ | ❌ | **削除** |
| `adapters/openai_adapter.py` | ❌ | ❌ | ❌ | ⚠️ 保留: 削除 or `@deprecated` 残置 |
| `adapters/anthropic_adapter.py` | ❌ | ❌ | ❌ | ⚠️ 保留: 削除 or `@deprecated` 残置 |
| `adapters/ollama_adapter.py` | ❌ | ❌ | ❌ | ⚠️ 保留: 削除 or `@deprecated` 残置 |
| `adapters/factory.py` | ❌ | ❌ | ❌ | ⚠️ 上記に連動 |
| `orchestrator.py` (ScriptOrchestrator) | ❌ (provider-agnostic) | ❌ | ❌ | ⚠️ 保留 |
| `topic_curator.py` | ❌ | ❌ | ❌ | ⚠️ 上記に連動 |
| `segment_generator.py` | ❌ | ❌ | ❌ | ⚠️ 上記に連動 |
| `metadata_generator.py` | ❌ | ❌ | ❌ | ⚠️ 上記に連動 |
| `fact_extractor.py` | ❌ | ❌ | ❌ | ⚠️ 上記に連動 |
| `fact_checker.py` | ❌ | ❌ | ❌ | ⚠️ 上記に連動 |
| `show_runner.py` | ❌ | ❌ | ❌ | ⚠️ 上記に連動 |
| `visual_palette_generator.py` | ◎ (Gemini 画像系) | ❌ | ❌ | **削除** |
| `image_prompt_generator.py` | ◎ (Gemini 画像系) | ❌ | ❌ | **削除** |
| `time_expressions.py` | ❌ (純粋 utility) | (間接的可能性) | ❌ | **保持** |
| `validators/` | ❌ (純粋 utility) | (間接的可能性) | ❌ | **保持** |
| `llm_factory.py` | △ ("gemini" ブランチあり) | ❌ | ❌ | **編集** ("gemini" ブランチ削除) |

### A.4 services/pipeline/ の責務

| ファイル | 用途 | 推奨判断 |
|---|---|---|
| `research_phase.py` | Perplexity 検索計画 + リサーチ実行 | **保持** (Perplexity 経路) |
| `scripting_phase.py` | `execute_fact_extraction_only` / `execute_curation_only` (HITL 単独実行) + `execute_scripting_phase` (Orchestrator → Script) | **要編集** |
| `production_phase.py` | VOICEVOX + FFmpeg | **保持** (provider 非依存) |
| `external_script_phase.py` | Step 3 で追加、VerifiedScript JSON ロード | **保持** (Step 3) |

### A.5 cost_calculator.py の用途

- `services/cost_calculator.py:107–151` の `calculate()` メソッドは `PerplexityUsage` と `LLMUsage` 両方を処理
- `usage.llm_usage` を iterate し全 provider の費用計算をサポート
- Perplexity リサーチ経路で常に依存（コストレポート生成）
→ **保持必須**（Perplexity コスト計算で使う）

### A.6 second_mode 引数

- `workflow.py:1771` の `run_workflow_sync(second_mode=...)` 引数
- `workflow.py:2054–2087` の `if second_mode:` 分岐は **`_execute_gradio_scripting_phase()` 専用** = Phase 1+2 (Gemini 台本生成) 専用フロー
- Perplexity リサーチ経路 / 外部台本モードでは second_mode 不使用
→ **削除可**

### A.7 main.py の phase 経路

| `--phase` | 削除可否 | 根拠 |
|---|---|---|
| `all` | **削除** | Gemini 台本生成必須 |
| `research` | 保持 | Perplexity のみ呼ぶ |
| `script` | **削除** | Gemini 台本生成必須 |
| `render` | 保持 | provider 非依存 |
| `external` | 保持 | Step 3 推奨経路 |

関連 CLI 引数: `--theme` / `--mode` / `--provider` / `--research-brief` のうち、`--theme` `--mode` は `research` 経路でも使うため保持、`--provider` は Gemini 台本生成のみで使うため **削除**、`--research-brief` は他経路で使われていないため **削除**。

### A.8 core/models/usage.py の構造

| 名前 | 行 | 削除可否 |
|---|---|---|
| `PerplexityUsage` | 7–14 | **保持** (Perplexity 経路) |
| `LLMUsage` | 18–44 | **保持** (provider-agnostic、cost_calculator が使う) |
| `GeminiUsage = LLMUsage` (alias) | 48 | **削除** (alias、import 元はコード編集で `LLMUsage` に置換) |
| `TotalUsage` | 59–94 | **保持** (`llm_usage: dict[str, LLMUsage]` を使う) |
| `CostBreakdown` | 97–110 | **保持** |

### A.9 外部台本モード経路の保護根拠（最終確認）

外部台本モードの実行パス（`main.py --phase external --verified-script ...` または Gradio UI からの `external_script_path` 経由）が、削除候補ファイルを参照しないことを確認:

```
main.py:elif args.phase == "external":
  → execute_external_script_phase()
    → RadioDirectorScriptLoader.load()
      → VerifiedScript.model_validate_json()
    → build_script_segments()
  → RadioScriptArtifact 構築
  → execute_production_phase()
    → VOICEVOX + FFmpeg + NVENC
```

外部台本モード経路は **GeminiClient / GeminiAdapter / orchestrator / agents / llm_factory のいずれも import / 参照しない**。LLM 呼び出しゼロ。削除作業の影響なし。

### A.10 Perplexity 経路の保護根拠

```
main.py --phase research:
  → execute_research_phase()
    → PerplexityResearcher.research_multi()  (deprecated warning は出るが動作)
    → ResearchBrief 生成
    → save_research_brief()
```

Perplexity 経路は **scripting_phase 配下を通らない**。`execute_research_phase` のみで完結し、ResearchBrief を `workspace/<session>/` に保存して終わる。後段の Gemini 台本生成は呼ばれない。削除作業の影響なし。

### A.11 テスト影響範囲（35 件中の分類）

| 削除対象 (Gemini / Orchestrator 経由) | 保持 (外部台本モード / Perplexity / 共通モデル) |
|---|---|
| `test_structured_output_response_schema.py` | `test_external_script_phase.py` |
| `test_prompt_pressure.py` | `test_verified_script_model.py` |
| `test_max_tokens_unification.py` | `test_radio_director_loader.py` |
| `test_logger_error_on_truncation.py` | `test_workflow_external_script_mode.py` |
| `test_orchestrator_curator_fallback.py` | `test_main_cli_verified_script.py` |
| `test_structured_facts_phase3.py` | `test_app_external_script_ui.py` |
| `test_topic_curator_tone_normalization.py` | `test_fact_checker.py` (FactCheckReport データモデルのみ、LLM 非依存) |
| `test_fact_extractor_self_inconsistency.py` | `test_fact_extractor.py` (FactSheet データモデルのみ、LLM 非依存) |
| `test_fact_extractor_two_phase.py` | `test_show_runner.py` (ShowPlan データモデルのみ) |
| `test_metadata_chapters.py` (一部) | `test_text_sanitizer.py` |
| `test_metadata_uses_script_fixed.py` | `test_voicevox_chapter_titles.py` |
| `test_chapter_naming.py` | `test_ffmpeg_renderer.py` |
| `test_metadata_description_format.py` (一部) | `test_jingle_index_based.py` |
| `test_segment_generator*.py` (該当ファイル全) | `test_two_story_mode.py` の Gemini 部分以外 |
| | `test_curation_result_validator.py` (Pydantic モデル単体) |
| | `test_thumbnail_regeneration.py` |

→ **削除予定: 約 10〜14 件**、**保持: 約 21〜25 件**

### A.12 旧経路の Mock データ

- `tests/mock_data/research.json` → **保持** (Perplexity モック)
- `tests/mock_data/script.json` → **削除** (Gemini script モック専用)
- `tests/mock_data/audio/combined_audio.wav` → **保持** (音声合成 mock)

---

## Part B: 削除方針（Yuru-Stoic 適用）

### B.1 削除確実な対象（依存関係なし、安全)

1. **services/script_generation/gemini_client.py** (クラス全体)
2. **services/script_generation/adapters/gemini_adapter.py**
3. **services/script_generation/visual_palette_generator.py**
4. **services/script_generation/image_prompt_generator.py**
5. **core/models/usage.py** の `GeminiUsage = LLMUsage` エイリアス（alias 行のみ削除、`LLMUsage` 本体は保持。import 元の `GeminiUsage` 参照を `LLMUsage` に書き換え）
6. **core/interfaces/script_generator.py** + `IScriptGenerator` 関連 export（GeminiClient が唯一の実装、削除可）
7. **services/pipeline/scripting_phase.py の `execute_fact_extraction_only` / `execute_curation_only`** 関数（HITL 単独実行用、Gemini 専用）
8. **services/pipeline/scripting_phase.py の `execute_scripting_phase`** 関数（Orchestrator 経由の Gemini 台本生成、外部台本モードでは別関数）
9. **services/script_generation/__init__.py** の re-export を整理

### B.2 編集対象（Gemini ブランチ削除、他は保持）

1. **services/script_generation/llm_factory.py**: "gemini" ブランチを削除（他 provider ブランチは @deprecated 残置の判断に依存）
2. **workflow.py**:
   - `create_script_generator` 関数: gemini 経路削除（他 provider は保留判断）
   - `create_research_plan` 経由の planning phase（line 784, 1406）: 削除
   - `execute_planning_phase` (line 755): 削除
   - `_execute_gradio_scripting_phase` (line 816): 削除
   - `run_workflow_sync` の **`second_mode` 引数 + 関連 2-Story Mode 実装**: 削除
   - `run_workflow_sync` の Phase 1 (planning) ブロック: 削除
   - `run_workflow_sync` の Phase 2 (`_execute_gradio_scripting_phase` 呼び出し) ブロック: 削除
   - `run_workflow_sync` の `theme` / `avoid_topics` 引数の取り扱い（外部台本モードでは VerifiedScript.metadata.title から自動上書きされるので、Perplexity 用にだけ意味がある → Perplexity research phase は run_workflow_sync を通らないので、この workflow から `theme`/`avoid_topics` 完全削除）
   - `_generate_youtube_metadata` の Gemini packaging prompt 経路（external_metadata=None のときの旧ロジック）: 削除し、external_metadata 必須化
3. **app.py**:
   - Generator タブの Deprecated アコーディオン全体を整理:
     - 削除: `theme_input` / `llm_provider_dropdown` / `avoid_topics_input` / `second_mode_dropdown` / `jingle_dropdown` / `jingle_path_input`
     - 保持 (アコーディオン外に移動): `research_mode_dropdown` (Perplexity モード選択)、`research_import_file` (Perplexity ResearchBrief import)
   - `generate_video` ハンドラから旧 LLM 引数を削除
   - イベントハンドラ inputs リストから削除コンポーネント参照を除去
   - `app.py:34, 709, 830` の AI プロデューサーモード handler を削除
4. **main.py**:
   - `--phase all` / `--phase script` 分岐を削除
   - `--phase` choices から "all", "script" を削除
   - `--provider` 引数を削除
   - `--research-brief` 引数を削除（他経路で未使用）
   - module docstring を更新
5. **services/pipeline/__init__.py**: `execute_curation_only` / `execute_scripting_phase` を re-export から削除
6. **README.md**: 旧経路の説明を整理、Step 4 完了の宣言

### B.3 ⚠️ 判断保留（アーキテクトレビューで決定）

下記は **provider-agnostic 設計**で、Gemini 専用ではない。Step 4 v2 のスコープでは Yuru-Stoic に従い **保持 + `@deprecated` 残置を推奨**。理由:

1. 削除しなくても外部台本モード + Perplexity リサーチが完全動作する
2. 将来 Ollama / OpenAI / Anthropic + Perplexity の組み合わせを再導入する余地を残す
3. テスト 8〜10 件の追加削除が必要になる（リスク増）
4. workflow.py / app.py の編集規模が拡大（リスク増）

| ファイル | 推奨 | 削除する場合の追加作業 |
|---|---|---|
| `services/script_generation/orchestrator.py` (ScriptOrchestrator) | 保持 + 注記 | Phase 2 経路全削除、関連テスト削除 |
| `services/script_generation/topic_curator.py` | 保持 + 注記 | 同上 |
| `services/script_generation/segment_generator.py` | 保持 + 注記 | 同上 |
| `services/script_generation/metadata_generator.py` | 保持 + 注記 | 同上 |
| `services/script_generation/fact_extractor.py` | 保持 + 注記 | 同上 |
| `services/script_generation/fact_checker.py` | 保持 + 注記 | factcheck_report.json 機能削除 |
| `services/script_generation/show_runner.py` | 保持 + 注記 | 同上 |
| `services/script_generation/adapters/openai_adapter.py` | 保持 | factory 経路の整理 |
| `services/script_generation/adapters/anthropic_adapter.py` | 保持 | 同上 |
| `services/script_generation/adapters/ollama_adapter.py` | 保持 | 同上 |
| `services/script_generation/adapters/factory.py` | 保持 | gemini ブランチのみ削除 |
| `services/script_generation/adapters/base.py` | 保持 | 共通インターフェース |

→ これらは Gemini 専用ではないため、本 Step では **そのまま物理保持**。`@deprecated` 注記を **クラス init level** で追加する程度に留める。

### B.4 削除順序（依存関係が安全に解消される順）

1. **テスト削除** (Gemini 関連テスト約 10〜14 件) — 既存テストが落ちる前に削除しておく
2. **mock_data/script.json 削除**
3. **app.py UI 編集** (Deprecated アコーディオン解体、Perplexity 用要素を独立アコーディオンに移動)
4. **main.py 編集** (`--phase all/script` 分岐削除、関連引数削除)
5. **workflow.py 編集** (Phase 1+2 ブロック削除、second_mode 削除、create_script_generator gemini ブランチ削除、Gemini 系 helper 削除)
6. **services/pipeline/scripting_phase.py 削除** (`execute_fact_extraction_only` / `execute_curation_only` / `execute_scripting_phase` 関数全削除)
7. **services/pipeline/__init__.py の re-export 整理**
8. **services/script_generation/llm_factory.py の "gemini" ブランチ削除**
9. **services/script_generation/__init__.py の re-export 整理**
10. **services/script_generation/gemini_client.py 削除**
11. **services/script_generation/adapters/gemini_adapter.py 削除**
12. **services/script_generation/visual_palette_generator.py 削除**
13. **services/script_generation/image_prompt_generator.py 削除**
14. **core/interfaces/script_generator.py 削除** (+ `core/interfaces/__init__.py` の export 整理)
15. **core/models/usage.py の `GeminiUsage` alias 削除** + import 元の置換 (`from core.models import GeminiUsage` → `LLMUsage` に統一)
16. **README.md 更新** (Step 4 完了宣言、削除済み機能の表記、外部台本モード推奨を強化)
17. **判断保留対象に `@deprecated` 注記を関数 init level で追加** (provider-agnostic ファイル群)

---

## Part C: Commit 構成案（細かく区切る）

各 commit で `pytest tests/ -q` 全 PASS を必須とする。SAVE / リセットの最小単位を保ち、Step 1〜3 と同じ細粒度。

| # | Commit | 主な変更 |
|---|---|---|
| 1 | `chore(tests): Gemini 台本生成専用テストを削除` | 約 10〜14 件のテスト削除 + tests/mock_data/script.json 削除 |
| 2 | `feat(ui): Generator タブから Gemini 台本生成入力欄を削除` | app.py: Deprecated アコーディオン解体、Perplexity 用要素を独立アコーディオンに移動、handler 配線整理 |
| 3 | `feat(cli): main.py から --phase all/script を削除` | main.py: 分岐削除 + 引数整理 |
| 4 | `feat(workflow): run_workflow_sync から Phase 1+2 ブロックを削除` | workflow.py: Phase 1+2 / second_mode / Gemini 系 helper 削除、metadata 経路を external_metadata 必須化 |
| 5 | `feat(pipeline): scripting_phase.py から Gemini 経路関数を削除` | services/pipeline/scripting_phase.py 全削除 + `__init__.py` 整理 |
| 6 | `feat(script_generation): GeminiClient + 関連を物理削除` | gemini_client.py / gemini_adapter.py / visual_palette_generator.py / image_prompt_generator.py 削除、llm_factory.py 整理 |
| 7 | `chore(interfaces/models): IScriptGenerator + GeminiUsage alias 削除` | core/interfaces/script_generator.py 削除 + core/models/usage.py の alias 削除 + import 元の `LLMUsage` 置換 |
| 8 | `chore(deprecated): provider-agnostic 経路に @deprecated 関数 level 注記` | orchestrator / agents / 残存 adapter に注記追加（実物理削除はしない） |
| 9 | `docs(readme): Step 4 v2 完了 + 推奨経路の明記` | README.md 更新 |

---

## Part D: テスト方針

### D.1 既存テストの保護

外部台本モード関連 (Step 3 で追加した 6 ファイル) と共通モデル単体テストは **全件保持**:
- `test_external_script_phase.py` / `test_verified_script_model.py` / `test_radio_director_loader.py` / `test_workflow_external_script_mode.py` / `test_main_cli_verified_script.py` / `test_app_external_script_ui.py`
- データモデル単体: `test_fact_checker.py` / `test_fact_extractor.py` / `test_show_runner.py` / `test_curation_result_validator.py`
- VOICEVOX / FFmpeg / metadata / publishing 系: `test_voicevox_chapter_titles.py` / `test_ffmpeg_renderer.py` / `test_jingle_index_based.py` / `test_text_sanitizer.py` / `test_metadata_uses_script_fixed.py` / `test_chapter_naming.py` / `test_metadata_chapters.py` / `test_metadata_description_format.py` / `test_thumbnail_regeneration.py`
- conftest.py の `mock_app_config` fixture は dummy keys のため保持

### D.2 削除対象テスト（Gemini / Orchestrator 経由のみ）

- `test_structured_output_response_schema.py`
- `test_prompt_pressure.py`
- `test_max_tokens_unification.py`
- `test_logger_error_on_truncation.py`
- `test_orchestrator_curator_fallback.py`
- `test_structured_facts_phase3.py`
- `test_topic_curator_tone_normalization.py`
- `test_fact_extractor_self_inconsistency.py`
- `test_fact_extractor_two_phase.py`
- `test_two_story_mode.py` の該当部分（second_mode 削除に伴い全削除）
- `test_workflow_external_script_mode.py` 内の旧 LLM との独立性確認テストは保持（external 経路を担保）

### D.3 新規テスト追加（Step 4 v2 での回帰防止）

| ファイル | 内容 |
|---|---|
| `tests/test_v2_gemini_path_removed.py` | 削除済みファイル / シンボルが import されないことの構造的契約テスト (~5 件) |
| `tests/test_workflow_external_only.py` | run_workflow_sync が external_script_path 必須になった契約テスト (~3 件) |

合計新規: 約 8 件

### D.4 E2E 動作確認

- 外部台本モード: `python main.py --phase external --verified-script tests/fixtures/verified_script_sample.json` で動画生成完走を再確認
- Perplexity 経路: `python main.py --phase research --theme "テスト" --mode trivia` で ResearchBrief.json が生成されることを確認 (実 API なし、mock 化または skip 可)

---

## Part E: リスクと回避策

| # | リスク | 影響 | 回避策 |
|---|---|---|---|
| 1 | `app.py` の Deprecated アコーディオン解体で event handler の wiring が壊れる (Step 3 で同じ警戒をしたリスク #4 の継続) | 旧 UI 操作不可 | アコーディオンは「外側→内側」順に編集。`generator_components` dict のキー名を変えない。コンポーネント参照名を保持。commit 2 後に Risk #4 同等の手動 smoke test を再実施 |
| 2 | `workflow.py` の Phase 1+2 ブロック削除でインデント崩れ / 残存変数参照エラー | 起動時エラー | 行単位ではなく function 単位で削除。削除後に linter (`python -c "import workflow"`) で構文確認 |
| 3 | `core/models/usage.py` の `GeminiUsage` alias 削除で import 元 14 ファイルが壊れる | 起動時 ImportError | 削除前に `grep -rn "GeminiUsage" core/ services/ workflow.py app.py main.py` で import 元を全部 `LLMUsage` に置換。テスト全 PASS で確認 |
| 4 | `services/pipeline/__init__.py` の re-export を間違って Perplexity / external phase を削除 | Perplexity / 外部台本モードが import 失敗 | re-export は Perplexity と external のみ残す。test_external_script_phase.py が回帰テストとして守る |
| 5 | `IScriptGenerator` 削除で型注釈が壊れる箇所 | 静的型エラー | 削除前に grep。削除後 `python -c "import workflow; import app"` で確認 |
| 6 | provider-agnostic な orchestrator + agents が「保持」なのに実際には誰も呼ばない dead code 化 | コードベースの不整合 | Yuru-Stoic 方針通り `@deprecated` 注記で明示。Step 5 (将来) で削除判断 |
| 7 | テスト件数が大幅減（約 -10〜-14、+8）でカバレッジが下がる | 品質劣化 | 残存テストは外部台本モード + Perplexity + データモデル + VOICEVOX/FFmpeg をカバーしており実質的なカバレッジは維持される |

---

## Part F: アーキテクトレビュー時の確認事項

| # | 項目 | 推奨判断 |
|---|---|---|
| 1 | provider-agnostic な orchestrator / agents / 他 adapter (Ollama/OpenAI/Anthropic) を **保持 + @deprecated 注記** で残すか **物理削除** するか | **保持 + 注記** (Yuru-Stoic 方針、外部台本モード + Perplexity への影響なし、将来再導入余地あり) |
| 2 | `tests/mock_data/script.json` を削除するか | **削除** (Gemini script mock 専用、保持の意味なし) |
| 3 | `--phase all` の代替経路を提供するか (例: `external --verified-script ... ; render`) | 不要 (外部台本モードで `external` 単独で完結する設計) |
| 4 | Ollama 経路の `--phase ollama` のような新規 CLI を導入するか | 不要 (本 Step スコープ外、将来 Step 5 で別途検討) |
| 5 | core/interfaces/script_generator.py の物理削除 vs 注記残置 | **物理削除** (GeminiClient が唯一の実装、Gemini 削除と同時に消える) |

---

## Part G: 修正対象ファイル一覧（commit 単位）

### Commit 1: テスト削除
- 削除: `tests/test_structured_output_response_schema.py`
- 削除: `tests/test_prompt_pressure.py`
- 削除: `tests/test_max_tokens_unification.py`
- 削除: `tests/test_logger_error_on_truncation.py`
- 削除: `tests/test_orchestrator_curator_fallback.py`
- 削除: `tests/test_structured_facts_phase3.py`
- 削除: `tests/test_topic_curator_tone_normalization.py`
- 削除: `tests/test_fact_extractor_self_inconsistency.py`
- 削除: `tests/test_fact_extractor_two_phase.py`
- 削除: `tests/test_two_story_mode.py`
- 削除: `tests/mock_data/script.json`

### Commit 2: app.py UI
- 編集: `app.py` (Deprecated アコーディオン解体、handler 配線整理)

### Commit 3: main.py CLI
- 編集: `main.py` (`--phase all/script` 削除、関連引数削除、docstring 更新)

### Commit 4: workflow.py
- 編集: `workflow.py` (Phase 1+2 / second_mode / Gemini helper 削除、metadata external 必須化)

### Commit 5: services/pipeline/
- 削除: `services/pipeline/scripting_phase.py`
- 編集: `services/pipeline/__init__.py` (re-export 整理)

### Commit 6: services/script_generation/
- 削除: `services/script_generation/gemini_client.py`
- 削除: `services/script_generation/adapters/gemini_adapter.py`
- 削除: `services/script_generation/visual_palette_generator.py`
- 削除: `services/script_generation/image_prompt_generator.py`
- 編集: `services/script_generation/llm_factory.py` ("gemini" ブランチ削除)
- 編集: `services/script_generation/__init__.py` (re-export 整理)

### Commit 7: interfaces / models
- 削除: `core/interfaces/script_generator.py`
- 編集: `core/interfaces/__init__.py` (`IScriptGenerator` export 削除)
- 編集: `core/models/usage.py` (`GeminiUsage = LLMUsage` alias 削除)
- 編集: 全 import 元 (約 14 ファイル) で `GeminiUsage` → `LLMUsage` 置換

### Commit 8: @deprecated 関数 level 注記
- 編集: `services/script_generation/orchestrator.py` の `ScriptOrchestrator.__init__` に warn
- 編集: `services/script_generation/topic_curator.py` の `TopicCurator.__init__` に warn
- 編集: `services/script_generation/segment_generator.py` の `SegmentGenerator.__init__` に warn
- 編集: `services/script_generation/metadata_generator.py` の `MetadataGenerator.__init__` に warn
- 編集: `services/script_generation/fact_extractor.py` の `FactExtractor.__init__` に warn
- 編集: `services/script_generation/fact_checker.py` の `FactChecker.__init__` に warn
- 編集: `services/script_generation/show_runner.py` の `ShowRunner.__init__` に warn
- 編集: `services/script_generation/adapters/openai_adapter.py` / `anthropic_adapter.py` / `ollama_adapter.py` の `__init__` に warn
- 編集: `services/script_generation/adapters/factory.py` の create メソッドに warn

### Commit 9: docs
- 編集: `README.md` (Step 4 v2 完了宣言、外部台本モード推奨を強化、削除機能リスト追加)
- 追加: `docs/step4_implementation_plan.md` (本プランを物理保存、レビュー追跡用)

### 新規テスト
- 追加: `tests/test_v2_gemini_path_removed.py` (構造的契約テスト約 5 件)
- 追加: `tests/test_workflow_external_only.py` (約 3 件)

---

## Part H: 削除「しない」もの（Yuru-Stoic 適用、明示）

- `services/research/` 全体 (PerplexityResearcher、保持指定)
- `services/pipeline/research_phase.py` (Perplexity 経路)
- `services/pipeline/production_phase.py` (provider 非依存)
- `services/pipeline/external_script_phase.py` (Step 3 推奨経路)
- `services/script_loading/` (Step 3)
- `services/cost_calculator.py` (Perplexity コスト計算で必須)
- `core/models/usage.py` の `PerplexityUsage` / `LLMUsage` / `TotalUsage` / `CostBreakdown`
- `core/models/research.py` の `ResearchSource` (publishing 共通利用)
- `core/interfaces/researcher.py` (Perplexity 経路の型契約)
- `core/interfaces/audio_synthesizer.py` / `video_renderer.py` / `script_loader.py` / `llm_port.py` (provider 非依存)
- UI の `research_mode_dropdown` / `research_import_file` (Perplexity 経路で使用、独立アコーディオンに移動)
- `services/script_generation/orchestrator.py` + agents (Yuru-Stoic、保留判断、@deprecated 注記のみ)
- `services/script_generation/adapters/openai_adapter.py` / `anthropic_adapter.py` / `ollama_adapter.py` (Yuru-Stoic、保留判断、@deprecated 注記のみ)
- `services/script_generation/llm_factory.py` ("gemini" ブランチのみ削除、他 provider ブランチは保持)
- `services/script_generation/time_expressions.py` / `validators/` (純粋 utility)

---

## 次のアクション

ExitPlanMode 呼び出し → ユーザー承認後の最初のアクション:
1. 本プランを `<repo>/docs/step4_implementation_plan.md` (= `E:\windsurf\auto_radio_generator\docs\step4_implementation_plan.md`) として保存
2. 実装は **行わず**、アーキテクトレビュー (Part F の判断点を含む) 待ち

Part F は推奨判断を提示済のため、アーキテクトが NG を出さない限り推奨通りで実装着手予定。
