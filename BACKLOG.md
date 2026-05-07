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

## [BACKLOG] Structured Output (Ollama / vLLM 共通) - JSON schema 強制 導入検討

**記録日**: 2026-04-24（初版「Ollama Structured Output」） / **更新日**: 2026-05-03（vLLM 移行を反映）
**発見経緯**: PR-E のプロンプト改善で効果不十分だった場合の次の一手として、調査報告で挙がった

### 内容
Ollama は `format` パラメータに JSON schema を渡すことで LLM 出力を schema に物理的に制約できる機能を提供している（2026-04 時点）。
**2026-05-03 追記**: GX10 移行 + プロキシ経由で実体は **vLLM (Qwen3-Next-80B)** にルーティングされる構成になった。vLLM は OpenAI 互換 API で `response_format={"type": "json_schema", "json_schema": {...}}` および `extra_body={"guided_json": ...}` をサポートしており、Ollama より安定した schema 強制が期待できる。本 BACKLOG は両バックエンドを対象に拡張。

プロンプトでの明示圧力（PR-E）はモデル依存で効果が不安定だが、Structured Output は **schema 層で省略を不可能にする** ため、title 欠落や facts=[] を構造的に防げる。
直近の関連修正: `fix(fact_extractor): facts エントリ string 形式の dict 正規化`（2026-05-03、提案 C）は短期防御層として実装済みだが、根治には schema 強制が必要。

### 実装想定
- `core/interfaces/llm_port.py` の `LLMRequest` に `response_schema: Optional[dict]` フィールド追加
- `services/script_generation/adapters/ollama_adapter.py` で `response_schema` を以下のいずれかで渡す:
  - **Ollama 経由（旧構成）**: `format` パラメータに schema dict を渡す
  - **vLLM 経由（現構成）**: OpenAI SDK の `response_format={"type": "json_schema", "json_schema": ...}` か、vLLM 固有の `extra_body={"guided_json": ...}` を使う
  - どちらも OpenAI 互換 API レイヤなので分岐は最小限で済む見込み
- 他プロバイダ（Gemini / OpenAI / Anthropic）対応は別フェーズ（JSON mode / response_format の差異吸収）
- 各エージェントの Pydantic モデル（`CuratedTopic` / `ExtractedFact`）から schema を自動生成（`model_json_schema()`）

### 前提条件
- 現行 vLLM サーバー（プロキシ越しの GX10）で `guided_json` または `response_format=json_schema` がサポートされていることの確認
- Qwen3-Next-80B が schema 指定下で安定動作するかの実検証
- 旧来の Ollama 直接構成で動かす場合のフォールバック分岐の要否

### 優先度
**中〜高に昇格**（2026-05-03 評価）。理由:
- vLLM 移行で Ollama 時代の「schema サポート不安」問題がクリア
- malformed facts (str エントリ等) の根治アプローチとして即効性
- 短期防御層（提案 C）が複数入ったが、schema 強制で一掃可能

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

---

## [RESOLVED] モデル変更検討（qwen3:8b → 中型モデル）

**記録日**: 2026-04-24（提案） / **解決日**: 2026-04-30（GX10 移行で実施）

GX10 (128GB) 推論サーバーへの移行に伴い、Mac Studio (32GB) の VRAM 制約で
使えなかった大型モデルへ切り替え可能となり、本 BACKLOG の主旨は実現した。

### 実施内容
- `orchestrator.curator_model`: qwen3:8b → **qwen3:32b**
- `orchestrator.segment_model`: gemma4:26b → **qwen3:32b**
- `orchestrator.json_model`: qwen2.5:14b → **qwen3:32b**
- `orchestrator.show_runner.model`: 空（curator フォールバック）→ **qwen3:32b** 明示
- `orchestrator.fact_extractor.model`: qwen2.5-coder:14b → **qwen2.5-coder:32b**

### 詳細
CHANGELOG.md「2026-04-30: GX10 推論サーバー移行に伴うモデル切替」を参照。

`script_generator.ollama.model`（デフォルトフォールバック）も `gemma4:26b` →
`qwen3:32b` に切替。UI ヘルスチェック表示も実行時モデル（curator_model）を
ping する形に修正済み（CHANGELOG 同セクション）。

### 残課題（軽微）
qwen3:32b の効果（title 欠落・facts=[] の発生頻度低下）は実運用観察待ち。
本 BACKLOG ではなく「PR-E 効果観察」の枠で追跡する。

---

## [RESOLVED-PARTIAL] ExtractedFact.category の実データ分布調査

**記録日**: 2026-04-23（提案） / **部分着地日**: 2026-05-02

GX10 移行後に主力となった qwen2.5-coder:32b が `イベント / 技術 / 定義` を
高頻度で出力し、SSOT 6 値外として WARNING を量産していたため、運用実態に
合わせて SSOT を 6 → 9 値に拡張した（Literal 拡張で対応）。

### 実施内容
- `core/models/fact_sheet.py::FactCategory` を 9 値に拡張
- `config/prompts.yaml > orchestrator.fact_extractor` の「## カテゴリの選び方」
  節に対応する 3 行を追加（既存「事件」も「ニュース性事件」に微修正して棲み分け）
- テスト 2 件を `..._six_values` → `..._nine_values` に rename + parametrize 拡張

### 詳細
CHANGELOG.md「2026-05-02: FactCategory に「イベント」「技術」「定義」を追加」を参照。

### 残課題
本 BACKLOG が掲げた「実データ分布の体系的集計」自体は未着手。fact_sheet.json
が数十件蓄積した時点で、9 値の使用比率や残存する未知値の頻度を集計する余地は残る。
ただし主因である「コードモデルが多用するカテゴリの SSOT 不在」は本対応で解消した。

---

## [LEARNED] FactExtractor 2 段階アーキテクチャ（markdown + regex）の実装失敗

**記録日**: 2026-05-07
**該当コミット**: `b17b44b` (実装) → `0705abe` (fix-json マージ) → 本エントリと同タイミングで revert
**該当ブランチ**: `feature/fact-extractor-two-phase` → `fix/factextractor-rollback`
**発見経緯**: 本運用検証 (Windows 機 / テーマ「睡眠と免疫」 / 2026-05-06)

### 実装内容（ロールバック済み）

SegmentGenerator の 2 段階パターン（Phase 1 markdown 生成 + Phase 2 regex parse）を
FactExtractor に横展開した。JSON 強制と FactSheet 構造化作業の同時実行が原因とされた
JSON 切断・enum 違反・facts=[] 化を構造的に解消する目的だった。

具体的な変更:
- Phase 1: `response_format="text"` で markdown を自由記述させる
  （`# FactSheet / ## テーマ要約 / ### Fact N` の固定フォーマット）
- Phase 2: 正規表現で markdown → Pydantic FactSheet
- max_tokens 8192 → 12288（30 件 × 約 6 行の markdown 余裕）
- prompts.yaml に `orchestrator.fact_extractor_creative` を新設
- 新規テスト 36 件で各分岐を網羅

### 本運用での失敗

期待していた効果と裏腹に、Qwen3.5-122B-A10B-NVFP4 (vLLM) で深刻な品質低下が発生:

| 指標 | 期待値 | 実測値 |
|---|---|---|
| ファクト抽出件数 | 30 件 | **1 件のみ** |
| 処理時間 | 〜470 秒（前回基準） | **2,105 秒（4 倍以上）** |
| `fact_sheet_phase1.md` の品質 | 構造化された markdown | 思考プロセスの漏出 + 英語の無限ループ |
| `/no_think` + `enable_thinking=false` の効き | 既存の SegmentGenerator では効いていた | 効かず |

### 根本原因（推定）

**markdown フィールドをモデルが「思考スペース」として使い始める。**

SegmentGenerator では markdown が「ラジオ台詞」という創造的タスクで、対話セリフ自体が
最終出力なので thinking と output の境界が自然に保てた。一方 FactExtractor は
**分析的・構造化タスク**（事実を厳選し型に整形する）であり、これに対して markdown の
自由フィールド（特に「出典」「主語」「記述」のような自由記述部分）を与えると、
モデルが「ここで考察を展開する」モードに入る。`/no_think` プレフィックスや
`chat_template_kwargs.enable_thinking=False` は thinking ブロックを抑制するが、
**出力本文中で思考が始まる**ケースは止められない。

結果として:
- markdown が「途中で思考が始まり、英語ループに陥り、length 切り詰めまで止まらない」
- 1 件目を書き終えた段階で max_tokens を使い切る
- Phase 2 regex parser に届くのは `### Fact 1` 一件のみ

### 学び

> **分析的・構造化タスク（事実抽出 / 統計的判断 / カテゴリ分類）は markdown 自由形式に向かない。**
> 創造的タスク（台詞生成 / シナリオライティング）と異なり、自由記述スペースが
> 与えられると thinking モデルはそこで「考察」を始め、決められた構造を破壊する。
> 構造化タスクには JSON モードや明示的な短い出力形式の方が安定する。

派生的な学び:
- `/no_think` や `enable_thinking=False` は **thinking ブロック** を抑制するが、
  本文中の思考漏出（"考察 in output"）には効かない
- SegmentGenerator で 2 段階パターンが成功したのは、markdown 内容が**そのまま音声化される
  最終物**で、モデルが「考察を書いてもどうせ全部使われる」という前提で振る舞ったため。
  「考察を絞り込んで構造化された結果を作る」必要がない
- 同じ 2 段階パターンを横展開する判断は、**タスクの性質（分析的 vs 創造的）** を
  必ず確認してから行うべき
- 本運用検証なしの理論先行（実機検証はしたが小サンプル fixture に留まっていた）
  リスクが顕在化。Windows 機での実運用テーマで動かすステップを踏むべきだった

### 残置: LLMRequest.response_schema 基盤

将来 vLLM の `response_format=json_schema` を別経路で再挑戦する余地を残すため、
以下の基盤は revert 対象から外して保持している:

- `core/interfaces/llm_port.py`: `LLMRequest.response_schema / response_schema_name /
  response_schema_strict` フィールド
- `services/script_generation/adapters/ollama_adapter.py`: `response_schema` →
  `response_format=json_schema` 変換ロジック
- `tests/test_structured_output_response_schema.py`: 上記基盤の単体テスト

これらは TopicCurator への適用も既に rollback 済（commit `5d2d764`）で、
**現時点では誰も使っていない眠った基盤**。ただし削除はしない（再挑戦時の起点）。

### 今後の再挑戦に向けた指針

FactExtractor の精度を改善したい場合の次の選択肢:

1. **JSON 経路のまま、より小さい単位の LLM 呼び出し**: 30 件を一括ではなく、
   3-5 件ずつ複数回に分けて呼び出す。max_tokens 圧迫を回避
2. **vLLM `response_format=json_schema` の再挑戦**: TopicCurator では品質劣化したが、
   FactExtractor は分析的タスクなので JSON schema 強制との相性が逆に良い可能性
3. **Pre-extracted structured_facts (Phase 3) への完全移行**: リサーチ側パイプラインで
   structured_facts を出力させ、台本側 FactExtractor は実行しない（
   `interface_spec.md v1.0` の本来の設計）。`FactSheet.from_structured_facts` は既に
   実装済み
4. **モデルの変更**: thinking モード強めの Qwen3.5 ではなく、構造化指示遵守が高い
   非-thinking モデル（Llama 系等）に切り替える

いずれの選択肢も「分析的タスクを markdown 自由形式に投げない」という本エントリの
学びは保持する。
