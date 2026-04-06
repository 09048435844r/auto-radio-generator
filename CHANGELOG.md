# 変更履歴

このプロジェクトの全ての重要な変更はこのファイルに記録されます。

フォーマットは [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) に基づいており、
このプロジェクトは [Semantic Versioning](https://semver.org/spec/v2.0.0.html) に準拠しています。

## [Unreleased]

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
