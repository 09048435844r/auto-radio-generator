# Step 3 実装プラン: auto-radio-generator 外部台本モード化

**版数:** 1.2 (Part C 全項目解決後)
**作成日:** 2026-05-09
**対象リポジトリ:** auto-radio-generator (Windows / E:\windsurf\auto_radio_generator)
**派生元ブランチ:** fix-json (HEAD = `905ff57`)
**作業ブランチ:** `feature/external-script-mode` ← 本プラン承認後に派生
**指示書:** `step3_auto_radio_generator_instructions.md` v1.0
**フェーズ:** プラン作成のみ（実装はアーキテクトレビュー後）

---

## Context

Mac Studio 側で運用される `radio_director` パイプライン (Step 1 完了済) が VerifiedScript JSON を生成するようになり、Windows 側の auto-radio-generator は動画化 (VOICEVOX / FFmpeg / NVENC) のみを担当する構成へ移行する。本 Step 3 では、VerifiedScript JSON 1 ファイルを手動配置するだけで動画生成が完了する経路 (= 外部台本モード) を新設する。

旧 LLM 経路 (Gemini Phase 1 / Phase 2 + Perplexity) は v1 では `@deprecated` 注記付きで物理保持し、運用が安定した後に Step 4 (v2) で完全削除する。

---

## Part A: 環境調査結果

### A.1 ブランチ状態 (2026-05-09 時点)

| 項目 | 値 |
|---|---|
| 派生元 | `develop` ブランチ (`merge-base = 9b4503f`) |
| `main` との関係 | `merge-base(main, fix-json) = 8687e45` (Step 0 調査時点)、`main..fix-json = 220 commits` 先行 |
| 現在 HEAD | `905ff57 revert(fact_extractor): 2段階アーキテクチャをロールバック（本運用失敗）` |
| テスト状態 | 379 件 pass、clean |

→ **Step 3 は fix-json から `feature/external-script-mode` を派生して実施**。main 派生は 220 commits 分の改善を失うため不採用。

### A.2 環境バージョン

| 項目 | 値・場所 |
|---|---|
| Pydantic | **v2** (`requirements.txt:7`、`field_validator` / `model_validator` を使用) |
| Gradio | **v4** (`requirements.txt:35`、`gr.File()` / `gr.Accordion()` を使用) |
| pytest | 最小設定 (`pytest.ini`、`testpaths = tests`、マーカーなし) |
| `tests/fixtures/` | **未存在**（既存 fixture は `tests/mock_data/`）→ 指示書通り新規作成 |
| `services/script_loading/` | **未存在** → 新規作成 |
| `output/` | `.gitignore` で `output/*/` 全除外済み → `output/imports/` に専用ルール不要 |
| `paths.output_dir` | `config.yaml:618-622` で `output` 固定 |

### A.3 Step 0 (= main) からの構造的差分（重要な再構成）

| 項目 | Step 0 (main) | 現状 (fix-json HEAD) | 影響 |
|---|---|---|---|
| `workflow.py` 行数 | 1,760 行 | 2,671 行 | Gradio 統合層を含む |
| `services/pipeline/` package | **存在しない** | **3 file** (`research_phase.py` / `scripting_phase.py` / `production_phase.py`) | ⚠️ 大幅な構造変更 |
| Phase 関数の実装場所 | `workflow.py` 直接 | `services.pipeline` に移行、workflow.py は**薄い委譲ラッパ** | Step 0 §7「workflow.py を薄く」が部分的に進行 |
| `main.py` import | "壊れている" 記載 | **clean、`services.pipeline` 経由で整備済** | ⚠️ 指示書 §2.2.4 broken import 修正は **不要** |
| 旧 LLM 経路 (削除候補) | 全現存 | **全現存** (services/research/, services/script_generation/, services/cost_calculator.py 等) | 削除は v2 で予定通り |
| `ResearchSource` 依存箇所 | publishing のみ | publishing **+ services/pipeline/scripting_phase.py** | 削除/移動はさらに困難 |

### A.4 既存の前例パターン（Step 3 で再利用）

#### research_import_filepath パターン
- `workflow.py:1872-1936`: `research_import_filepath` 引数で `research_brief.json` をロード → Phase 1 (Perplexity) を bypass
- `app.py:2015-2026`: アコーディオン「📂 リサーチデータのインポート」+ `gr.File(file_types=[".json"])`
- `nonlocal theme` で SSOT 上書き、`enable_research = False` で API スキップ

→ Step 3 は **同じ構造**で `external_script_path` を導入。違いは Phase 1+2 まとめて bypass する点 (新規 `external_script_phase` でラップ)。

### A.5 VerifiedScript JSON 実構造（添付 fixture 実機確認）

```
{
  "script": {
    "show_spec": {...},
    "segments": [
      {
        "segment_type": "intro" | "deep_dive" | "conclusion",
        "topic_index": int,
        "title": str,
        "turns": [{"speaker": "A"|"B", "text": str}, ...]
      },
      ...   // 計 5 segments (intro + 3 deep_dive + conclusion)
    ],
    "metrics": {...}
  },
  "metrics": {...},          // 抽出統計（Step 3 では未使用、loader は無視）
  "warnings": [...],         // 警告ログ（Step 3 では未使用、loader は無視）
  "metadata": {              // ★ Script への変換ターゲット
    "title": str,
    "thumbnail_title": str,  // max 15 字 (§4.3 SSOT)
    "description": str,      // 50〜2000 字
    "hashtags": [str, ...],  // 3〜15 件
    "chapters": [{"timestamp": str, "title": str}, ...],
    "references": []         // ★ 既知制約 (§4.4)、空配列を正常系として扱う
  }
}
```

添付 fixture 実機確認: 5 segments / `references=[]` / `metadata` 必須 6 フィールドすべて存在 / 31,634 bytes。

---

## Part B: 実装プラン

### B.1 設計方針 (アーキテクト判断反映後)

1. **SSOT**: VerifiedScript JSON 1 ファイル受け取りで Phase 1+2 完全 bypass
2. **既存パターン整合 (§2.2.1 Option B 採用)**: `services/pipeline/external_script_phase.py` を新設し、既存 `research_phase` / `scripting_phase` / `production_phase` と対称な構造を取る。`workflow.py:run_workflow_sync` は新 phase の呼び出しラッパーを追加するだけの薄い変更
3. **Append-Only**: 既存テスト無変更、新規追加のみ。既存ファイル変更は最小限 (`workflow.py` / `app.py` / `main.py` / `services/pipeline/__init__.py`)
4. **Deprecated 残置**: 旧 LLM 経路は `@deprecated` 注記付きで物理保持。**module レベル `warnings.warn` ではなく関数/クラス init レベル**を採用してテスト suite のノイズを回避（要アーキテクト確認、Part C 参照）
5. **Pydantic 厳格化**: `RadioDirectorScriptLoader` は `VerifiedScript.model_validate_json` で input を厳密検証、silent fallback 禁止
6. **broken import 修正サブタスク削除**: 指示書 §2.2.4 の `PerplexityClient` 削除は **不要** (現状 main.py の imports は clean)

### B.2 ファイル変更一覧

#### B.2.1 新規追加（6 ファイル）

| ファイル | 役割 | 主要シグネチャ・契約 |
|---|---|---|
| `core/interfaces/script_loader.py` | `IScriptLoader` ABC、既存 ABC 群 (`IResearcher` / `IScriptGenerator` / `IAudioSynthesizer` / `IVideoRenderer`) と同列の薄い interface | `class IScriptLoader(ABC):`<br>`@abstractmethod`<br>`def load(verified_script_path: Path) -> Script` |
| `core/models/verified_script.py` | Mac 側 SSOT の Windows 側読み取り用 view モデル | `class VerifiedScript(BaseModel)` / `ShowSpec` / `Segment` / `Turn` / `VideoMetadata` / `Chapter` / `SourceRef`<br>v2 idiom (`Field(min_length=...)` / `field_validator`)<br>`segment_type: Literal["intro", "deep_dive", "conclusion"]`<br>冒頭 docstring に「Mac 側 `radio_director/models/verified_script.py` と同期、変更時は両方更新」を明記 |
| `services/script_loading/__init__.py` | 新規 package | `from .radio_director_loader import RadioDirectorScriptLoader` |
| `services/script_loading/radio_director_loader.py` | `IScriptLoader` 実装本体 | `class RadioDirectorScriptLoader(IScriptLoader):`<br>`def load(verified_script_path: Path) -> Script`<br>helper: `_flatten_segments_to_sections`, `_build_synthesis_segments` |
| `services/pipeline/external_script_phase.py` | **新 phase** (Option B 採用): VerifiedScript ロード → Script 構築 → Phase 1+2 完全 bypass | `async def execute_external_script_phase(`<br>`    verified_script_path: Path,`<br>`    session_manager: SessionManager,`<br>`    config: AppConfig,`<br>`    callbacks: Optional[ProgressCallback] = None,`<br>`) -> ExternalScriptPhaseResult`<br>戻り値 dataclass: `script: Script, segments: List[ScriptSegment], pre_built_metadata: Dict[str, str]`<br>既存 `RadioScriptArtifact` と互換のあるフィールドで Phase 3 (production) に直接渡せる |
| `tests/fixtures/verified_script_sample.json` | 添付 fixture を配置 (31,634 bytes、`references=[]`) | テスト時の入力。実装時は `C:\Users\09048\Downloads\verified_script_sample.json` をコピーして配置 |

#### B.2.2 既存ファイル変更（4 ファイル）

| ファイル | 変更概要 | 行数目安 |
|---|---|---|
| `services/pipeline/__init__.py` | `execute_external_script_phase` を re-export | +2 |
| `workflow.py` | `run_workflow_sync` に `external_script_path: Optional[Path] = None` 追加。既存 `research_import_filepath` 分岐の **直後**に新分岐を挿入し `execute_external_script_phase` を呼ぶ。Phase 1+2 を skip。`_generate_youtube_metadata` に `external_metadata: Optional[dict] = None` 引数を追加し、external 経路では Gemini packaging prompt を skip して dict をそのまま採用 | +35 / -0 |
| `app.py` | Generator タブに「外部台本モード」アコーディオン (default open) + ファイルピッカー追加。旧 LLM 入力 (theme/research_mode/avoid_topics) を「Deprecated: v2 で削除予定」アコーディオンに収納。**handler 配線は変更せず、コンポーネント参照キーを保持** | +30 / -10 |
| `main.py` | CLI 引数 `--verified-script <path>` 追加 → 内部で `execute_external_script_phase` を呼ぶ phase を新設 (`--phase external` も併設)。旧 LLM 経路 (`PerplexityResearcher.__init__` / `GeminiClient.generate` / 旧 Generator handler) に関数 level `@deprecated` 注記。**broken import 修正は実施しない** | +20 / -0 |

#### B.2.3 `RadioDirectorScriptLoader.load()` 変換ロジック詳細

```
INPUT: verified_script_path (Path)

1. ファイル読み込み + Pydantic 検証
   text = path.read_text(encoding="utf-8")
   vs = VerifiedScript.model_validate_json(text)   # 不正 JSON は ValidationError

2. Script.sections 構築 (segments を平坦化)
   sections = []
   for segment_idx, seg in enumerate(vs.script.segments):
       for turn_idx, turn in enumerate(seg.turns):
           dt = DialogueTurn(
               speaker=turn.speaker,
               text=turn.text,
               turn_type=TurnType.DIALOGUE,
               # 先頭 turn のみ section / chapter_title を付与
               section=seg.segment_type if turn_idx == 0 else None,
               chapter_title=seg.title if turn_idx == 0 else None,
           )
           sections.append(dt)

3. references を URL 文字列リストに変換 (空配列は空のまま)
   ref_urls = [str(ref.url) for ref in vs.metadata.references]   # HttpUrl → str

4. Script 構築
   script = Script(
       title=vs.metadata.title,
       sections=sections,
       thumbnail_title=vs.metadata.thumbnail_title,
       description=vs.metadata.description,
       hashtags=list(vs.metadata.hashtags),
       references=ref_urls,
   )
   return script
```

#### B.2.4 `execute_external_script_phase()` 内部フロー

```
INPUT: verified_script_path, session_manager, config, callbacks

1. callbacks.log("外部台本モード: VerifiedScript ロード中")
   loader = RadioDirectorScriptLoader()
   script = loader.load(verified_script_path)

2. ScriptSegment リスト構築 (production_phase が chapter rendering で使う)
   segments = _build_script_segments_from_verified(vs, ...)
   ※ 既存 voicevox_client._build_segment_index_map と互換

3. pre_built_metadata 構築 (workflow._generate_youtube_metadata の external 経路用)
   pre_built_metadata = {
       "title": vs.metadata.title,
       "thumbnail_title": vs.metadata.thumbnail_title,
       "description": vs.metadata.description,
       "hashtags": list(vs.metadata.hashtags),
   }

4. session に保存 (HITL / 再実行のため)
   session_manager.save_script_artifact(...)

5. return ExternalScriptPhaseResult(script, segments, pre_built_metadata)
```

#### B.2.5 旧 LLM 経路への `@deprecated` 注記方針

**採用方針: 関数/クラス level `warnings.warn(DeprecationWarning)` (module level は採用しない)**

| 対象 | 場所 | 警告タイミング |
|---|---|---|
| `PerplexityResearcher.__init__` | `services/research/perplexity_client.py` | 初期化時 |
| `GeminiClient.generate` の冒頭 | `services/script_generation/gemini_client.py` | 呼び出し時 |
| 旧 Generator タブ UI ハンドラ (旧 theme/research_mode 経路の entry function) | `app.py` 内 | UI から旧モード起動時 |

理由: module 先頭 `warnings.warn` だと `import` のたびに発火 → 既存テスト 379 件で大量警告がログに混入。関数 level なら **実際に旧経路が呼ばれた時のみ**警告 (外部台本モードでは呼ばれず、テスト上もノイズなし)。

⚠️ アーキテクトレビュー時の判断点 (Part C-2 参照)。指示書 §2.3 の module-level pattern とは差分あり。

### B.3 Commit 構成案 (8 commits)

各 commit で `pytest tests/ -q` 全 PASS を必須とする。Step 1 と同じ細粒度。

| # | Title | 主な変更 | 新規テスト |
|---|---|---|---|
| 1 | `feat(models): VerifiedScript Pydantic v2 モデル追加` | `core/models/verified_script.py` 新規 | `tests/test_verified_script_model.py` (8 件) |
| 2 | `feat(interfaces): IScriptLoader ABC 追加` | `core/interfaces/script_loader.py` 新規 | `tests/test_script_loader_interface.py` (3 件) |
| 3 | `feat(loader): RadioDirectorScriptLoader 実装` | `services/script_loading/` package 新規 + `tests/fixtures/verified_script_sample.json` 配置 | `tests/test_radio_director_loader.py` (12 件) |
| 4 | `feat(pipeline): execute_external_script_phase 新規追加` | `services/pipeline/external_script_phase.py` 新規 + `__init__.py` 更新 | `tests/test_external_script_phase.py` (6 件) |
| 5 | `feat(workflow): run_workflow_sync に external_script_path 経路を追加` | `workflow.py` 拡張 (`run_workflow_sync` 引数 + 新分岐 + `_generate_youtube_metadata` external 対応) | `tests/test_workflow_external_script_mode.py` (4 件) |
| 6 | `feat(ui): Generator タブに外部台本モードアコーディオンを追加` | `app.py` UI 再構成 (旧入力を deprecated アコーディオンに移動) | UI テストは Gradio launch を patch するため最小限 (1 件: 構造的契約の regex 確認) |
| 7 | `feat(cli): main.py に --verified-script 引数 + 旧経路に @deprecated 注記` | `main.py` CLI 拡張 + 関数 level deprecated 警告追加 | `tests/test_main_cli_verified_script.py` (3 件) |
| 8 | `docs(readme): 外部台本モードを README に追記` | `README.md` セクション追加 + Step 4 削除予定項目を明示 | n/a |

各 commit は **独立して revert 可能**な粒度を維持。

### B.4 テスト戦略

#### B.4.1 新規テストファイル一覧

| ファイル | 対象 | 件数 |
|---|---|---|
| `tests/test_verified_script_model.py` | `VerifiedScript` Pydantic v2 モデル: 必須/optional フィールド・min/max 制約・`references=[]` 正常系・破損 JSON 拒否・`thumbnail_title` 15 字制約 | 8 |
| `tests/test_script_loader_interface.py` | `IScriptLoader` ABC: abstractmethod 強制・型契約・実装が `Script` を返すこと | 3 |
| `tests/test_radio_director_loader.py` | `RadioDirectorScriptLoader.load()`: fixture 読み込み / 全フィールド変換 / `references=[]` / segments+turns 平坦化 / 先頭 turn の section+chapter_title 付与 / HttpUrl→str / 不正 JSON 拒否 / segment_type 正規化 / 最低 turn 数検証 | 12 |
| `tests/test_external_script_phase.py` | `execute_external_script_phase()`: loader を呼ぶ / Script + segments + pre_built_metadata を返す / 不正 JSON で例外伝播 / session_manager 連携 / Phase 1/2 完全 bypass | 6 |
| `tests/test_workflow_external_script_mode.py` | `run_workflow_sync` 経路: external_script_path None で従来動作 / 指定時に新 phase 経由 / `_generate_youtube_metadata` の external_metadata 経路 / 旧 research_import との独立性 | 4 |
| `tests/test_main_cli_verified_script.py` | `main.py --verified-script`: 引数受け入れ / loader を呼ぶ経路 / 旧 `--phase` との非干渉 | 3 |
| (commit 6 内) | `app.py` 外部台本アコーディオン構造の regex 確認 (workflow.py の研究 import 構造的テストと同パターン) | 1 |

**新規テスト合計: 37 件**

#### B.4.2 テスト fixture

- `tests/fixtures/verified_script_sample.json`: 添付 fixture を **そのまま** 配置 (31,634 bytes、`references=[]`)
  - 実装時: `C:\Users\09048\Downloads\verified_script_sample.json` を `tests/fixtures/verified_script_sample.json` にコピー (commit 3 に含める)
  - サイズ確認: 31,634 bytes
- 異常系テスト用に inline JSON 文字列を使う (壊れた構造で Pydantic ValidationError を発生させるケース)

#### B.4.3 既存テストへの影響評価

- 既存 379 件は **触らない** (指示書 §3.2)
- workflow.py 変更が既存 `research_import` 経路テストの回帰テストとして機能する
- main.py CLI 拡張は既存 phase 経路と独立 (新引数追加のみ)
- `@deprecated` 注記は関数 level のため import 時には発火しない → 既存テストへの影響なし

#### B.4.4 E2E 動作確認 (手動、commit 完了後の最終確認)

1. 添付 fixture を `output/imports/smoke_test/verified_script.json` に配置
2. Gradio UI 起動 → 「外部台本モード」アコーディオンでファイル選択 → 動画生成
3. 期待結果:
   - VOICEVOX 合成 + FFmpeg レンダリング完了
   - `metadata.txt` に VerifiedScript.metadata 内容が反映 (Gemini API 呼ばれず)
   - 概要欄の参考文献欄が空 (`references=[]` の正常系)
   - VOICEVOX chapter は VerifiedScript の segment.title に基づく
4. 別 run で旧 LLM 経路でも動画生成成功を確認 (deprecated 警告がログに出る)

### B.5 リスクと回避策

| # | リスク | 影響 | 回避策 |
|---|---|---|---|
| 1 | VerifiedScript の `metadata.title` が 15 字超 (Mac 側 SSOT で制約は thumbnail_title のみ、title は無制限) | UI / metadata.txt 表示崩れ | Pydantic 検証は spec 通り `thumbnail_title` のみ厳格化、`title` 側は YouTube API truncation の既存パターンに任せる |
| 2 | `segment_type` が "intro"/"deep_dive"/"conclusion" 以外 (spec 外) | loader で例外 → 動画生成停止 | `Literal["intro", "deep_dive", "conclusion"]` で型固定。Mac 側 SSOT と同期管理 |
| 3 | `references=[]` で `build_video_description` が落ちる | 概要欄組み立て失敗 | `metadata_builder.py:65` で空配列対応済 (前タスクで確認)、loader でも空配列を素通し |
| 4 | **旧 Generator UI のハンドラ配線がアコーディオン化で壊れる** (§2.2.3) | 旧モード回帰失敗 | **実装段階で確認するリスク項目として明記**。アコーディオンは入力コンポーネントを包むだけにし、コンポーネント ID と event handler キー参照は不変に保つ。`generator_components` dict のキー名を変えない。commit 6 完了時に旧モード起動 smoke test を手動実施 |
| 5 | autouse fixture (`tests/conftest.py:14-18` の `mock_gradio_launch`) が UI 構築で副作用を起こす | 既存テスト失敗 | アコーディオン追加だけなら component 構築は通常通り行われ、launch は patch されているため副作用なし。ただし commit 6 完了後にフルテスト実施で確認 |
| 6 | `@deprecated` を module-level で実装すると pytest が警告で汚染 | テストログ可読性低下、最悪 -W error 設定下で fail | 関数/クラス level で実装 (Part B.2.5 参照)。アーキテクトレビュー後に最終決定 |
| 7 | Mac 側 VerifiedScript モデル仕様が後で変わる | Windows 側 view モデルとの不整合 | view モデル冒頭 docstring に同期注記、`tests/fixtures/verified_script_sample.json` を Mac 側 fixture から再取得して再配置するフローをドキュメント化 |
| 8 | 添付 fixture サイズ (31KB) が repo に追加される | repo 肥大化 | 31KB は許容範囲。1 fixture のみで Mac 側でも既に git tracked |
| 9 | `services/pipeline/__init__.py` の re-export 追加が既存 import を壊す | テスト fail | re-export は addition のみ、既存名前空間に上書きしない |
| 10 | 新 phase の `ExternalScriptPhaseResult` dataclass が既存 `RadioScriptArtifact` と shape 違いで production_phase が混乱 | Phase 3 失敗 | `ExternalScriptPhaseResult` を `RadioScriptArtifact` と互換になるよう (`script: Script, segments: List[ScriptSegment], visual_identity: Optional[VisualIdentity] = None`) 設計する。production_phase 側の既存呼び出しコードを再利用 |

### B.6 所要時間見積

| Phase | 内訳 | 見積 |
|---|---|---|
| 実装本体 | commit 1〜7 (モデル + ABC + loader + new phase + workflow + UI + CLI) | 6〜8 時間 |
| テスト作成 | 新規 37 件 + 既存テストとの突合 | 2〜3 時間 |
| ドキュメント | commit 8 (README) | 1 時間 |
| 動作確認 | 手動 E2E (fixture 1 件 + 旧経路 1 件) | 1〜2 時間 |
| **合計** | | **10〜14 時間** |

短縮要因: 既存 `research_import_filepath` 経路がテンプレート、Pydantic v2 / services.pipeline パターンが既存コードベースに揃っている。
拡大要因: app.py UI 再構成の handler 配線確認、E2E は実環境 (VOICEVOX + RTX 4070) 前提。

### B.7 Acceptance Criteria 対応マトリクス

| §5 項 | 内容 | 対応 commit |
|---|---|---|
| 5.1.1 | VerifiedScript JSON 配置 → 動画生成完了 | 1〜7 (E2E は最終手動確認) |
| 5.1.2 | 旧 LLM 経路で依然動画生成可能 | 既存テスト + commit 6 で UI 触っても旧 handler 不変 + commit 7 で deprecated 警告のみ追加 |
| 5.1.3 | `references=[]` でも動画生成完了 | commit 3 (loader テスト) + commit 5 (workflow 統合) |
| 5.2.1 | 既存テスト全 PASS | 各 commit で必須 |
| 5.2.2 | 新規テスト全 PASS | 各 commit の単体テスト |
| 5.2.3 | 旧 LLM 経路 deprecated 残置 | commit 7 で関数 level 注記 |
| 5.2.4 | Mac 側 fixture が Windows 側 loader で読める | commit 3 で fixture 配置 |
| 5.3.1 | README に「外部台本モード」セクション | commit 8 |
| 5.3.2 | v2 削除予定の明示 | commit 8 |

### B.8 Step 4 (v2) への申し送り

実装後の完了報告で明示する事項 (指示書 §7-6):
- 旧 LLM 経路の物理削除 (`services/research/`, `services/script_generation/`, `services/cost_calculator.py`, `core/interfaces/script_generator.py`, `researcher.py`, `core/models/usage.py` の Gemini/Perplexity 部分, 旧 Generator タブ UI, Manual タブ Step A/B, `main.py` 旧 phase 経路)
- `run_workflow_sync(script: Script, ...)` 純化 (external_script_path / theme などの引数整理)
- VerifiedScript の `references` 充足 (Mac 側 Phase B/C プロンプトに `[src=N][TIER]` 出典タグ生成を追加)
- `core/models/research.ResearchSource` の扱い (publishing が依存しているため、移動 or 残置の判断)
- `services/pipeline/scripting_phase.py` 内の `ResearchSource` import 整理

---

## Part C: アーキテクトレビュー時の確認事項 (全項目解決済)

| # | 項目 | 判断 |
|---|---|---|
| 1 | ブランチ戦略 | ✅ **解決済**: fix-json から `feature/external-script-mode` 派生 |
| 2 | §2.2.1 実装場所 | ✅ **解決済**: Option B (services.pipeline に新 phase 追加) 採用 |
| 3 | §2.2.4 broken import 修正 | ✅ **解決済**: 該当サブタスクは削除、`--verified-script` CLI と `@deprecated` 注記のみ実施 |
| 4 | 旧 Generator UI ハンドラ配線維持 | ✅ **解決済**: リスク #4 として明記、実装段階で確認 |
| 5 | `@deprecated` 実装方針 | ✅ **解決済**: **関数/クラス level** を採用 (Plan B.2.5 提案通り)。指示書 §2.3 の module level コード例は撤回 (How への過度な踏み込み)。理由: module level だと import 時に発火し既存 379 件のテストでログ汚染。関数/クラス level なら実運用で旧経路が使われた時のみ警告 |
| 6 | テスト fixture 配置場所 | ✅ **解決済**: 仕様通り `tests/fixtures/` (新規ディレクトリ) で確定。既存 `tests/mock_data/` とは別運用 |
| 7 | CLI 引数命名 | ✅ **解決済**: `--verified-script <path>` で確定 (`--script` は既存の RadioScriptArtifact 用と衝突するため別名採用) |
| 8 | commit 8 (README) の独立性 | ✅ **解決済**: 8 commits 構成で独立 (commit 7 に統合しない) |

---

## 次のアクション

ExitPlanMode 呼び出し → ユーザー承認後の最初のアクション:
1. 本プランを `<repo>/docs/step3_implementation_plan.md` (= `E:\windsurf\auto_radio_generator\docs\step3_implementation_plan.md`) として保存
2. 実装は **行わず**、アーキテクトレビュー待ち

Part C は全項目解決済のため、本プランで合意済の方針が確定状態。
