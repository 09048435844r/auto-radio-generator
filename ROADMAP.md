# Auto Radio Generator - Development Roadmap

> **Created:** 2026-02-07  
> **Base Version:** v3.6.1 (HITL Mode + Bug Fixes)  
> **Last Updated:** 2026-04-23  
> **Author:** AI Tech Lead (Cascade)

---

## 🏆 Concept & Philosophy

**Auto Radio Generator** は、テーマを入力するだけで「リサーチ → 台本生成 → 音声合成 → 動画レンダリング → メタデータ生成」を全自動で行うラジオ動画生成システムです。

### "Input Minimal, Data Maximal" 開発哲学

今後の拡張は、以下の3原則に基づいて設計します。

1. **Data Lake Strategy（コンテンツ資産化）**
   - 生成プロセスの中間データ（プロンプト、APIレスポンス、コスト、ユーザー評価）を全て Raw JSON で蓄積し、将来の自己改善・分析に活用する。
2. **Input Minimal（自動化の徹底）**
   - 動画生成だけでなく、アップロード・テーマ選定・スケジューリングまで、人間の手作業を極限まで削減する。
3. **Future-Proof（疎結合）**
   - 特定の AI モデル（Gemini / Perplexity）に依存しすぎず、インターフェース単位で差し替え可能な構成を維持・強化する。

---

## 📊 Current Status (v3.6.1)

### Core Pipeline
- [x] **Research Phase** — Perplexity API による5モード対応リサーチ（debate / voices / trivia / weekly_digest / lecture）
- [x] **AI Producer** — Gemini による検索計画の自動作成（テーマ → 検索クエリ生成）
- [x] **Script Generation** — Multi-LLM Provider対応（Gemini / OpenAI / Anthropic）による構造化台本生成
- [x] **Audio Synthesis** — VOICEVOX による2話者音声合成 + ASS字幕生成
- [x] **Video Rendering** — FFmpeg による動画レンダリング（背景 + BGM + 字幕 + スペクトラム）
- [x] **Thumbnail Generation** — Pillow + BudouX による自動サムネイル画像生成
- [x] **Metadata Packaging** — Gemini によるタイトル・概要文・チャプター自動生成

### YouTube Description Robustness（2026-02 更新）
- [x] **Text Sanitizer Module** — `services/publishing/text_sanitizer.py` を新設し、YouTube向けテキスト正規化・制御文字除去・長さ制限を実装
- [x] **Line Break Preservation** — サニタイズ時に `\x09(Tab)`, `\x0A(LF)`, `\x0D(CR)` を保持し、概要欄の構造崩れを防止
- [x] **Resilient Title Fetching** — `chardet` によるエンコーディング検出を導入し、URLタイトル取得の耐障害性を強化
- [x] **Reference 3-line Format** — 参考文献を `📄 タイトル / 🔗 URL / 空行` の3行構造に統一
- [x] **Section Spacing Rule** — セクション見出し前2行、見出し後0〜1行の余白ルールを `metadata_builder.py` に実装
- [x] **Output Tail Trimming** — 概要欄末尾の不要空行をトリムし、投稿フォーマットを安定化
- [x] **Regression Tests Added** — `tests/test_text_sanitizer.py` / `tests/test_metadata_description_format.py` を追加し、改行保持と書式を自動検証

### v3.5.0 New Features（Hierarchical Agentic Workflow）
- [x] **TopicCurator** — リサーチデータから意外性・具体性・議論性の3軸で2〜3トピックを厳選
- [x] **SegmentGenerator** — intro / deep_dive / conclusion を独立したAPI呼び出しで生成
- [x] **ScriptOrchestrator** — 全体統括・文脈管理・セグメント統合を担当
- [x] **Context Continuity** — 各セグメントの context_summary を次セグメントに引き継ぎ
- [x] **Infinite Scalability** — セグメント単位で生成するため max_output_tokens の壁を回避
- [x] **Feature Flag** — config.yaml > orchestrator.enabled で新旧を切り替え可能（デフォルト: false）
- [x] **Cost Optimization** — キュレーションは軽量モデル（gemini-2.5-flash）を使用
- [x] **Progress Feedback** — 各セグメント生成の進捗をリアルタイム表示
- [x] **Retry Logic** — セグメント単位で最大2回リトライ、部分失敗にも対応
- [x] **JSON Robustness** — Unterminated string エラーを防止する堅牢化
  - max_output_tokens を十分に確保（TopicCurator: 8192, MetadataGenerator: 4096）
  - response_mime_type: "application/json" を使用しない（切断の原因となるため）
  - finish_reason=MAX_TOKENS を検出して警告
  - 4段階のサニタイズ処理（コードブロック除去、JSON抽出、制御文字除去、空白除去）
  - エラー時は完全な生レスポンステキストをログ出力（デバッグ用）
  - MetadataGeneratorはnon-fatalでフォールバック動作
- [x] **Documentation** — docs/script_orchestrator_architecture.md に詳細設計書を作成

### v3.4.0 Features（Multi-LLM Provider Support）
- [x] **LLM Provider Factory** — プロバイダー名から適切なクライアントを生成するファクトリーパターン実装
- [x] **OpenAI Integration** — Structured Outputs (`client.beta.chat.completions.parse`) による確実なJSON出力
- [x] **Anthropic Integration** — Tool Calling による構造化出力の強制
- [x] **UI Provider Selection** — Gradio UIのドロップダウンで3プロバイダー（Gemini/OpenAI/Anthropic）を動的切り替え
- [x] **Backward Compatibility** — デフォルトは `gemini`、既存機能は無変更で動作
- [x] **Configuration Extension** — `config.yaml` に各プロバイダーのモデル設定を追加
- [x] **Environment Variables** — `.env` に `OPENAI_API_KEY` と `ANTHROPIC_API_KEY` を追加

### v3.1.x New Features
- [x] **NVENC GPU Acceleration** — NVIDIA GPU によるハードウェアエンコード（h264_nvenc）、CPU 自動フォールバック付き
- [x] **Mock Development Mode** — API 課金なしでワークフロー全体をテスト可能（`tests/mock_data/` 使用）
- [x] **UI Progress Visualization** — Gradio 進捗バーで各フェーズの状況をリアルタイム表示
- [x] **Backward Compatibility** — 旧 JSON 形式（`speaker_id` / `dialogue`）の自動変換バリデータ
- [x] **JSON Mode Patch** — Gemini API の Native JSON Mode 有効化、正規表現パーサー撤廃

### Architecture
- [x] **Interface-Based Design** — `IScriptGenerator` / `IResearcher` / `IAudioSynthesizer` による疎結合設計
- [x] **Pydantic Models** — 型安全なデータバリデーション + JSON シリアライゼーション
- [x] **Dual Entry Points** — Gradio Web UI (`app.py`) + CLI (`main.py`)
- [x] **Settings Persistence** — `user_settings.json` によるユーザー設定の永続化
- [x] **Cost Calculator** — API 使用量トラッキング + コストレポート生成

### Recent Achievements（直近の達成事項）
- [x] **ShowRunner - Show Structure Planner (2026-04-23)** — Curator 選定後に番組全体の構成（アーク・トピック間ブリッジ・トーン・導入フック・締め戦略）を設計する新エージェントを導入。台本のダイジェスト感を解消し、因果でつながる物語構造を生成可能に
  - 新モジュール: `core/models/show_plan.py`（`ShowPlan` / `TopicBridge` データモデル）、`services/script_generation/show_runner.py`（`TopicCurator` と同型の `ILLMPort` エージェント）
  - パイプライン統合: `ScriptOrchestrator` に Step 1.5 を追加。`SegmentGenerator` の `generate_intro/deep_dive/conclusion` に `show_plan_hint: Optional[str]` 引数を追加し、ブリッジ意図をプロンプトへ defensively 差し込む
  - 永続化: `SessionManager.save_show_plan()` / `load_show_plan()` / `has_show_plan()` を実装。実行後は `workspace/{session_id}/show_plan.json` に自動保存、再実行時は自動ロード
  - プロンプト: `config/prompts.yaml` に `orchestrator.show_runner` システムプロンプトを新設（5軸「アーク／フック／ブリッジ／締め／トーン」で計画させる）
  - 設定: `config.yaml > orchestrator.show_runner.enabled` で ON/OFF 切替。Pydantic モデル上の既定値は `false`（後方互換）、同梱の `config.yaml` では `true` で有効化済み
  - HITL 対応基盤: `execute_scripting_phase(preset_show_plan=...)` を追加。人間が編集済み `show_plan.json` をセッションに置けば自動で反映（将来の Gate 2b UI 向け）
  - 失敗時フォールバック: ShowRunner が LLM エラーを起こしても警告ログのみで従来フロー継続（`show_plan=None`）
  - 回帰テスト: `tests/test_show_runner.py`（10 件） — モデル往復、JSON パース耐性、プロンプト差し込み、後方互換、SessionManager 往復をカバー
  - 動作検証済み: Ollama `qwen3:8b` で 3トピック + 4ブリッジの ShowPlan が正しく生成されることを実機確認（2026-04-23）
- [x] **TopicCurator - Defensive Title Fallback (2026-04-23)** — ローカル LLM（qwen3:8b 等）が稀に `title` フィールドを省略した JSON を返す問題に対し、`key_facts[0]` → `selection_reason` → プレースホルダの順でタイトルを合成するフォールバックを追加
- [x] **HITL Gate 2a - DataFrame Truthiness Fix (2026-04-23)** — `_show_curation_editor` で pandas.DataFrame が暗黙の bool コンテキストで評価され `ValueError` を吐くバグを修正。`len(df) > 0` による明示的な空判定に置換
- [x] **Research Data Reusability (2026-04-15)** — 自動モードで生成したリサーチデータの再利用機能を実装
  - `output/[session_id]/research_brief.json` を自動保存（インポート機能で再利用可能）
  - 既存の `research.json` は参照用として維持（後方互換性を完全保持）
  - ディスク使用量は微増（+10 MB程度、全体の0.08%）
  - 実装箇所: `workflow.py`（通常モードと2-Story Modeの両方）
  - 関連ドキュメント: `docs/RESEARCH_DATA_FUTURE_IMPROVEMENTS.md`
- [x] **Pre-Jingle Pause Feature (2026-04)** — ジングル再生前に自然な一拍（間）を挿入する機能を追加
  - `config.yaml` に `pre_jingle_pause_sec` 設定を追加（デフォルト: 0.5秒）
  - セグメント終了からジングル開始までの間に呼吸するような自然なポーズを挿入
  - 音声トラック（VoicevoxClient）とビデオタイムライン（TimelineCalculator）の両方で対応
  - リスナー体験の向上（ジングルが唐突に始まらず、より聴きやすい構成に）
- [x] **BGM Ducking Robustness (2026-04)** — ジングル再生中のBGM抑制機能の堅牢性を大幅に向上
  - ゼロ除算バグの修正（BGM音量が0の場合のクラッシュを防止）
  - 音量逆転バグの修正（ダッキングレベル検証により、ジングル中にBGMが大きくなる異常を防止）
  - 設定アクセスの最適化（初期化時にキャッシュし、メソッド呼び出しごとの冗長な処理を削減）
  - ジングル尺ゼロの安全チェック（不正な音声ファイルによるビデオタイミング計算の異常を防止）
- [x] **Unit Testing Environment** — `pytest` + `pytest-mock` を導入し、`tests/` 配下で単体テストを実行可能化
- [x] **CI/CD Foundation (pre-commit)** — `git commit` 時に `pytest` を自動実行し、失敗時はコミットをブロックするフックを導入
- [x] **Regression Prevention (FFmpeg Path Handling)** — Windows向けパスエスケープ処理をヘルパーメソッド化し、変換ロジックの回帰テストを追加
- [x] **Docs & Config Maintenance** — README/requirements/configコメントを現行実装に合わせて更新
- [x] **Topic Overlay Delivery** — チャプター開始行に連動した話題オーバーレイ表示を導入し、視認性を改善
- [x] **Mock Operation Hardening** — Mock実行時のアップロード自動無効化と、UIの専用実行ボタン運用を標準化
- [x] **Test Freeze Countermeasure** — テスト時の Gradio `launch()` 誤起動を抑止し、pre-commit での無限待機リスクを低減

### Next Priority（最優先）
- [ ] ⭐ **Scheduler（定期自動生成）の運用実装**（テーマ入力の手動作業をゼロ化）

### Known Gaps（哲学に基づく課題分析）

| カテゴリ | 課題 | 影響 |
|---------|------|------|
| **データ活用** | プロンプト履歴の分析UIが未整備 | 良い生成パターンの再利用に手間がかかる |
| **データ活用** | 実行ログの横断検索機能が弱い | 過去実行の比較がしづらい |
| **運用自動化** | テーマ選定が毎回人間入力 | 定期運用に人手が必要 |
| **手動運用** | テーマ選定が毎回人間入力 | 定期運用に人手が必要 |
| **手動運用** | BGM / 背景画像の選定が手動 | テーマとの不一致リスク |
| **コスト管理** | Usage追跡とコスト計算がGemini専用設計 | OpenAI/Anthropic使用時のコスト計算が不正確 |
| **技術的負債** | 音声スペクトラム機能が未使用のまま残存 | コードの複雑性増加、保守コスト |

---

## 📅 Future Roadmap (Proposal)

### 🚧 Phase 4: Data Asset & Logs（データの資産化）

> **目的:** 生成プロセスの中間データを「資産」として蓄積し、将来の分析・自己改善の基盤を構築する。

- [x] **Structured Execution Log**
  - 実行ごとに `execution_record.jsonl` へ以下を追記:
    - 実行日時、テーマ、リサーチモード、使用モデル
    - 送信したプロンプト（system / user）の全文
    - API 生レスポンス（パース前の raw text）
    - 生成パラメータのスナップショット（`config.yaml` + `UIOverrides` の実行時値）
    - 出力ファイルパス一覧
  - フォーマット: JSONL（1行1レコード、append-only で高速書き込み）

- [x] **Cost Tracking（コスト追跡・月次推移）** ⭐ 重点項目
  - 各生成ごとの API コスト（Gemini / Perplexity / VOICEVOX）を `cost_history.jsonl` に記録
  - 記録項目:
    - `timestamp`: 実行日時
    - `theme`: テーマ
    - `gemini_input_tokens`, `gemini_output_tokens`: Gemini トークン使用量
    - `perplexity_tokens`: Perplexity トークン使用量
    - `voicevox_phrases`, `voicevox_duration_sec`: VOICEVOX 使用量
    - `cost_gemini_usd`, `cost_perplexity_usd`, `cost_total_usd`: 各 API コスト（USD）
    - `render_duration_sec`, `total_duration_sec`: 処理時間
  - UI にダッシュボード追加:
    - 月次コスト推移グラフ（Gradio `gr.Plot`）
    - 直近 N 回の生成コスト一覧テーブル
    - 月間合計 / 平均コスト表示
  - 目的: **ランニングコストの可視化と予算管理**

- [ ] **Multi-Provider Usage Tracking Refactoring（マルチプロバイダー対応のUsage追跡リファクタリング）** 🔧 技術的負債解消
  - **現状の問題点:**
    - `GeminiUsage` クラスが全プロバイダー（Gemini/OpenAI/Anthropic）で共用されており、名前が不適切
    - `CostCalculator` がGeminiのレート（$1.25/$5.00 per 1M tokens）しか持たず、OpenAI/Anthropicのコスト計算が不正確
    - コストレポートが常に「Gemini」と表示され、実際の使用プロバイダーが不明瞭
  - **リファクタリング方針:**
    - `core/models/usage.py` に `LLMUsage` クラスを新設し、プロバイダー名を含む汎用的な構造に変更
      ```python
      @dataclass
      class LLMUsage:
          provider: str  # "gemini" | "openai" | "anthropic"
          model_name: str
          input_tokens: int
          output_tokens: int
          request_count: int
      ```
    - `TotalUsage` クラスの `gemini: GeminiUsage` を `llm: LLMUsage` にリネーム（後方互換性のため段階的移行）
    - `CostCalculator` にプロバイダー別レートを追加:
      - OpenAI (gpt-4o-mini): Input $0.15/1M, Output $0.60/1M
      - Anthropic (claude-3-5-sonnet): Input $3.00/1M, Output $15.00/1M
    - コスト計算ロジックを `usage.provider` に応じて適切なレートを選択するよう修正
    - コストレポートの表示を「Gemini」固定から動的プロバイダー名表示に変更
  - **移行戦略:**
    - 既存の `GeminiUsage` は互換性のため残し、`LLMUsage` のエイリアスとして定義
    - 新規コードは `LLMUsage` を使用し、段階的に移行
    - `execution_record.jsonl` / `cost_history.jsonl` のスキーマに `provider` フィールドを追加
  - **期待効果:**
    - 正確なプロバイダー別コスト計算とレポート表示
    - 将来の新規LLMプロバイダー追加時の拡張性向上
    - コードの可読性と保守性の改善

- [ ] **Feedback Loop（ユーザー評価記録）**
  - 生成完了後に UI で 👍 / 👎 + 自由コメントを入力可能に
  - 評価データを `feedback.jsonl` に蓄積
  - 将来的にプロンプト改善の教師データとして活用

- [ ] **Output Index（生成物インデックス）**
  - `output/` 配下の分散データを横断検索可能にするインデックスファイル
  - テーマ・日時・評価・コストでフィルタリング可能

- [ ] **Research Data Import Enhancement（リサーチデータインポート機能の拡張）** 🔄 中期実装候補
  - **現状:** 自動モードで生成した `research_brief.json` のみインポート可能（2026-04-15実装済み）
  - **課題:** 既存の165ファイルの `research.json`（5フィールド、シンプル形式）が再利用できない
  - **実装内容:**
    - ファイル形式の自動判定機能（`research_brief.json` vs `research.json`）
    - `research.json` → `ResearchBrief` への自動変換ロジック
    - 欠損フィールド（`queries`, `angle` など）の補完処理
    - ユーザーがファイル形式を意識せずにインポート可能に
  - **期待効果:**
    - 既存の全リサーチデータが再利用可能に
    - ユーザビリティの向上
    - 後方互換性の最大化
  - **実装難易度:** ⭐⭐⭐☆☆（中程度）
  - **推定工数:** 2-3日
  - **関連ドキュメント:** `docs/RESEARCH_DATA_FUTURE_IMPROVEMENTS.md`（案2）

- [ ] **Research Data Model Unification（リサーチデータモデルの統一）** 🔧 長期実装候補
  - **現状:** 2つの `ResearchResult` クラスが存在（dataclass版とPydantic版）+ `ResearchBrief`
  - **課題:** データモデルの重複によるコードの複雑性（17ファイルに影響）
  - **実装内容:**
    - `ResearchResult` (dataclass) を削除
    - `ResearchResult` (Pydantic) を削除
    - すべて `ResearchBrief` に統一
    - 保存処理の統一（`research.json` 廃止、`research_brief.json` のみ保存）
    - 変換処理の削減（ResearchBrief ↔ ResearchResult 変換が不要に）
  - **期待効果:**
    - データモデル数: 3つ → 1つ（-67%）
    - 保存処理の箇所: 2箇所 → 1箇所（-50%）
    - 変換処理の箇所: 2箇所 → 0箇所（-100%）
    - コードの複雑性削減、長期的なメンテナンス性向上
  - **実装難易度:** ⭐⭐⭐⭐☆（高）
  - **推定工数:** 5-7日
  - **前提条件:**
    - Import Enhancement（案2）が実装済み
    - 十分な移行期間（6ヶ月以上）
    - ユーザーへの事前周知
  - **関連ドキュメント:** `docs/RESEARCH_DATA_FUTURE_IMPROVEMENTS.md`（案3）

---

### 🚀 Phase 5: Full Automation（完全自動化）

> **目的:** 動画生成の「先」にある作業を自動化し、テーマ入力すら不要な完全自律運用を実現する。

- [x] **YouTube Auto-Uploader**
  - YouTube Data API v3 自動アップロードを実装済み
  - Google YouTube Data API v3 による自動投稿
  - アップロード対象: 動画ファイル（`.mp4`）、サムネイル（`.png`）
  - 自動設定: タイトル、概要欄（チャプター付き）、タグ、カテゴリ、公開設定
  - OAuth 2.0 認証フロー（初回のみブラウザ認証、以降はリフレッシュトークン）
  - アップロード結果（動画 URL、ステータス）を `execution_record.jsonl` に追記

- [ ] **Scheduler（定期自動生成）**
  - 指定日時に自動でトレンドを検索 → テーマ選定 → 生成 → アップロード
  - APScheduler による cron ライクなスケジューリング
  - config.yaml に `scheduler` セクション追加:
    ```yaml
    scheduler:
      enabled: false
      cron: "0 18 * * MON,THU"  # 毎週月・木の18:00
      auto_upload: true
      trend_source: "google_trends"
    ```

- [ ] **Auto Theme Selection（テーマ自動選定）**
  - Google Trends API / X(Twitter) API からトレンドトピックを自動取得
  - 過去の生成履歴（`execution_record.jsonl`）と照合し、重複テーマを自動除外
  - テーマ候補を Gemini でラジオ向けに再構成

- [ ] **Smart Asset Matching（素材自動選定）**
  - テーマのムード分析（Gemini）に基づき、BGM / 背景画像を自動マッチング
  - `assets/` 内のファイルにメタデータタグ（明るい / 落ち着いた / ニュース系 等）を付与

---

### 🎨 Phase 6: Advanced Content Optimization & SEO

> **目的:** 生成物のクオリティを商用レベルに引き上げ、視聴者体験を最適化する。

- [ ] **Advanced Visuals（動的テロップ演出）**
  - キーワードハイライト（重要語句の色変化・拡大）
  - 感情に応じたテロップスタイル変更（驚き → 赤、解説 → 青）
  - テロップアニメーション（フェードイン、スライドイン）

- [ ] **Audio Quality Validation（音声品質自動検証）**
  - 無音区間の異常検出（長すぎる無音、音割れ）
  - 字幕タイミングと音声の同期検証
  - 自動リトライ（品質基準未達の場合に再合成）

- [ ] **A/B Testing Infrastructure（A/Bテスト基盤）**
  - サムネイル・タイトルの複数候補を自動生成
  - YouTube Analytics API と連携し、CTR（クリック率）データを収集
  - Phase 4 の Feedback Loop と統合し、最適なパターンを学習

- [ ] **Multi-Voice Support（多話者対応）**
  - VOICEVOX 以外の音声合成エンジン対応（COEIROINK, Style-Bert-VITS2 等）
  - 3人以上のパーソナリティによるパネルディスカッション形式

- [ ] **Multi-Language Support（多言語対応）**
  - 英語 / 中国語等の台本生成・音声合成
  - 字幕の多言語同時生成

- [ ] **AI 駆動のリッチな概要欄生成**
  - Gemini API 等を活用し、生成台本から要約（Summary）と重要キーワードを抽出して概要欄を構成
  - Perplexity API 等で取得した参考文献リンクを自動で整理し、概要欄へ掲載

- [ ] **自動タイムスタンプ（Chapters）の生成**
  - 各セクションの音声生成時間を計算し、`00:00 オープニング` 形式のチャプターリストを概要欄へ自動挿入
  - YouTube のキーモーメント機能に対応し、視聴者が目的情報へ即アクセスできる導線を最適化

- [ ] **字幕・翻訳・コメント自動化**
  - 字幕（SRT）の自動生成と YouTube への字幕トラック登録を実装
  - タイトル・説明文・字幕の多言語翻訳を自動化し、Global SEO を強化
  - 公開直後に台本要約 + 参考文献リストをコメント投稿し、可能であれば固定（Pin）を実施
  - API 制約で固定不可の場合は、投稿のみ自動化 + 固定依頼通知を送る運用を検討

- [ ] **設計メモ（実装ヒント）**
  - `YouTubeClient` に `insert_comment(video_id, text)` などのメソッドを追加
  - ワークフロー最終工程（アップロード・再生リスト追加の後段）でコメント投稿処理を呼び出す構成を想定
  - `workflow.py` の動画生成フェーズで各パートの累積時間を算出し、チャプター付き概要欄を `YouTubeClient.upload_video(..., description=...)` へ渡す実装を想定

---

## 🔧 Technical Debt（技術的負債）

### 音声スペクトラム機能の削除

**現状:**
- v3.5.0時点で、動画レンダリング時の音声スペクトラム（波形）表示機能が実装されているが、実際には使用されていない
- UIからは非表示化されているが、コード全体に機能が残存している

**影響範囲:**
1. **UIレイヤー (`app.py`)**
   - `spectrum_checkbox` コンポーネントが `visible=False` で残存
   - `generate_video()` 関数の引数 `enable_spectrum: bool` が全ての呼び出し箇所に存在
   - `UIOverrides` データクラスに `enable_spectrum` フィールドが含まれる
   - 設定保存機能 (`user_settings.json`) に `enable_spectrum` が記録される

2. **ワークフローレイヤー (`workflow.py`)**
   - `UIOverrides` クラスに `enable_spectrum: bool` フィールドが定義
   - ワークフロー実行時に `enable_spectrum` が引き回される

3. **動画レンダリングレイヤー (`services/video_rendering/ffmpeg_renderer.py`)**
   - `_build_ffmpeg_command()` メソッド内に波形表示の条件分岐ロジックが残存
   - `enable_spectrum` パラメータに基づいて FFmpeg フィルターを切り替える処理
   - スペクトラム関連の設定値（`spectrum_color`, `spectrum_mode`）が `config.yaml` に定義

4. **設定ファイル (`config.yaml`)**
   - `video_renderer.enable_spectrum`, `spectrum_color`, `spectrum_mode` などの設定項目

**削除の難易度: 🟡 中程度**
- 単純な機能削除だが、影響範囲が広く、以下の作業が必要:
  1. UI コンポーネントの完全削除
  2. 関数シグネチャからの `enable_spectrum` 引数削除（10箇所以上）
  3. データクラスのフィールド削除と既存設定ファイルのマイグレーション
  4. FFmpeg コマンド生成ロジックの簡素化
  5. 設定ファイルのスキーマ更新
  6. 既存の `user_settings.json` との後方互換性確保

**削除のメリット:**
- コードの複雑性削減（約150行の削除見込み）
- 関数シグネチャの簡素化
- 設定項目の削減による保守性向上
- 新規開発者の学習コスト削減

**削除のリスク:**
- 既存の設定ファイル (`user_settings.json`) を持つユーザーへの影響
- 過去の実行ログ (`execution_record.jsonl`) に `enable_spectrum` フィールドが記録されている場合の互換性

**推奨アプローチ:**
1. **Phase 1: 非推奨化（Deprecation）** - 現在完了
   - UIから非表示化（`visible=False`）✅
   - 内部的には機能を維持し、後方互換性を確保 ✅

2. **Phase 2: 段階的削除（将来のメジャーバージョンアップ時）**
   - v4.0.0 などのメジャーバージョンアップ時に実施
   - マイグレーションスクリプトを提供し、既存設定ファイルを自動変換
   - CHANGELOG に破壊的変更として明記

3. **Phase 3: 完全削除**
   - 上記の影響範囲すべてからコードを削除
   - テストケースの更新
   - ドキュメントの更新

**優先度: 🔵 低（機能的な問題はなく、保守性の改善が主目的）**

---

## 🔧 Future Maintenance（今後の課題 / メンテナンス）

> **方針:** 現在は Python 3.10.6 環境で安定動作しているため、開発効率を優先して **2026年10月（サポート期限）まで現行環境を維持**する。  
> 一方で、Google API ライブラリのサポート期限を踏まえ、中長期の保守性確保のため計画的に移行を進める。

- [ ] **Python 3.11/3.12 への移行検討**
  - 理由: `google-api-core` の Python 3.10 サポート終了への対応（期限: 2026-10-04）
  - 時期目安: **2026年 夏〜秋頃**（プロジェクトが安定したタイミング）
  - 注意点:
    - Gradio 周辺ライブラリの互換性検証
    - iZotope 関連ツール（利用時）の互換性検証
    - FFmpeg 連携・既存レンダリング処理の回帰確認
    - 既存の API クライアント（Gemini / Perplexity / YouTube）接続テスト

---

## 🧩 Tech Stack Overview

### Current（v3.6.1）

| Layer | Technology | Role |
|-------|-----------|------|
| **Runtime** | Python 3.10+ | コアランタイム |
| **Web UI** | Gradio 4.0+ | ブラウザベース UI |
| **AI (Script)** | Gemini / OpenAI / Anthropic | 台本生成（プロバイダー選択可能）・メタデータ生成 |
| **AI (Research)** | Perplexity (OpenAI-compatible) | テーマリサーチ |
| **Audio** | VOICEVOX Engine | 音声合成（GPU 推奨） |
| **Video** | FFmpeg (NVENC) | 動画レンダリング（GPU 高速化） |
| **Image** | Pillow + BudouX | サムネイル生成 |
| **Data** | Pydantic 2.x | データモデル・バリデーション |
| **Config** | PyYAML + python-dotenv | 設定管理 |
| **CLI** | Rich | コンソール出力装飾 |

### Future Candidates（将来導入候補）

| Technology | Phase | Role |
|-----------|-------|------|
| **SQLite / JSONL** | Phase 4 | 実行ログ・コスト履歴・評価データの永続化 |
| **YouTube Data API v3** | Phase 5 | 動画の自動アップロード・Analytics 連携 |
| **APScheduler** | Phase 5 | 定期自動生成のスケジューリング |
| **Google Trends API** | Phase 5 | トレンドトピックの自動取得 |
| **Matplotlib / Plotly** | Phase 4 | コストダッシュボードの可視化 |

---

## 📐 Design Principles（設計原則）

今後の開発で遵守すべき原則:

1. **Interface First** — 新しいサービスは必ず `core/interfaces/` に抽象クラスを定義してから実装する
2. **Config Driven** — ハードコードを避け、全ての設定値は `config.yaml` で管理する
3. **Append-Only Logging** — データは削除せず追記のみ。JSONL 形式で蓄積する
4. **Graceful Degradation** — 外部サービス障害時は自動フォールバック（GPU → CPU、API → Mock）
5. **Zero Manual Steps** — 最終目標は「テーマ入力すら不要」な完全自律運用
6. **Lean Commit Rhythm** — コミット時は軽量チェック（構文チェック）を基本とし、全体テストは手動で計画実行する

---

*Auto Radio Generator v3.6.1 | "Input Minimal, Data Maximal"*
