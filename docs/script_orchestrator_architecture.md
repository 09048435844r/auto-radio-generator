# ScriptOrchestrator アーキテクチャ設計書

**作成日**: 2026年3月22日  
**バージョン**: v3.5.0  
**目的**: 長尺・高密度ラジオ台本を安定生成するための新アーキテクチャ

---

## 1. 背景と課題

### 1.1 旧アーキテクチャの問題点

従来の台本生成は **単一API呼び出し** で全セリフを一度に生成していました。

```
リサーチデータ（3000〜5000文字）
  ↓
[単一API呼び出し]
  - システムプロンプト: 2000文字
  - ユーザープロンプト: リサーチ全文 + テーマ + 除外トピック
  - max_output_tokens: 16384（Gemini API上限）
  ↓
Script（80〜120ターン）
```

**課題**:
1. **ダイジェスト化の誘発**: リサーチデータが膨大な場合、LLMが「すべてを浅く紹介」しようとし、深掘りが不十分
2. **トークン上限による途切れ**: 長尺台本（150ターン超）を生成しようとすると `MAX_TOKENS` で出力が途切れる
3. **JSONパースエラーのリスク**: 出力が途切れた場合、不完全なJSONが返され、パースに失敗する
4. **スケーラビリティの欠如**: リサーチデータ量や台本長に応じた柔軟な対応が困難

### 1.2 新アーキテクチャの要求仕様

1. **情報の深掘り保証**: 特定トピックを「狭く深く」語る仕組み
2. **無限のスケーラビリティ**: 台本長が150ターン超でも安定生成
3. **文脈とキャラクターの連続性**: 分割生成でも会話の流れが自然
4. **ユーザー体験の維持**: 進捗状態を適切にフィードバック

---

## 2. アーキテクチャ概要

### 2.1 Hierarchical Agentic Workflow

新アーキテクチャは **3つのエージェント** が段階的に処理を行います。

```
┌─────────────────────────────────────────────────────────────┐
│ ScriptOrchestrator (司令塔)                                  │
│  - 全体統括・文脈管理・セグメント統合                         │
└─────────────────────────────────────────────────────────────┘
         │
         ├─ Step 1: TopicCurator (キュレーター)
         │    └─ リサーチデータ → CuratedTopic × 2〜3個
         │
         ├─ Step 2: SegmentGenerator (セグメント生成)
         │    ├─ intro (導入)
         │    ├─ deep_dive_1 (深掘り1)
         │    ├─ deep_dive_2 (深掘り2)
         │    └─ conclusion (まとめ)
         │
         └─ Step 3: Integration (統合)
              └─ 全セグメント → Script
```

### 2.2 処理フロー

```
リサーチデータ（3000〜5000文字）
  ↓
[TopicCurator] (gemini-2.5-flash)
  - 意外性・具体性・議論性の3軸で評価
  - 上位2〜3トピックを選定
  ↓
CuratedTopic × 2〜3
  - title: "トピックタイトル"
  - content: 詳細情報（500〜800文字）
  - key_facts: ["ファクト1", "ファクト2", ...]
  - tone: "驚き" | "議論" | "解説" | ...
  ↓
[SegmentGenerator] (gemini-3.1-pro-preview)
  ├─ intro (10〜20ターン)
  │   └─ context_summary → 次へ引き継ぎ
  ├─ deep_dive_1 (25〜45ターン)
  │   └─ context_summary → 次へ引き継ぎ
  ├─ deep_dive_2 (25〜45ターン)
  │   └─ context_summary → 次へ引き継ぎ
  └─ conclusion (10〜20ターン)
  ↓
[ScriptOrchestrator]
  - 全セグメントの turns を結合
  - DialogueTurn の後方互換変換
  ↓
Script（80〜150ターン）
```

---

## 3. コンポーネント詳細

### 3.1 TopicCurator

**責務**: リサーチデータから面白いトピックを選定

**入力**:
- `ResearchResult`: Perplexityから得たリサーチ結果（全文）
- `target_count`: 選定するトピック数（デフォルト: 3）

**出力**:
- `CurationResult`:
  - `topics: List[CuratedTopic]`: 選定されたトピック（優先度順）
  - `curator_reasoning: str`: 選定理由（デバッグ用）

**評価軸**:
1. **意外性**: 一般的な常識と異なる情報か
2. **具体性**: 数字・人名・日付・エピソードが含まれるか
3. **議論性**: 賛否が分かれる、または「なぜ？」と問いたくなるか

**使用モデル**: `gemini-2.5-flash`（コスト削減）

**プロンプト**: `config/prompts.yaml > orchestrator.curation`

---

### 3.2 SegmentGenerator

**責務**: 1つの台本セグメントを生成

**セグメントタイプ**:
- `intro`: 番組の掴み、テーマ提示、トピック予告
- `deep_dive`: 1トピックの深掘り（key_factsを会話に織り込む）
- `conclusion`: 学びのまとめ、オチ、クロージング

**入力**:
- `theme: str`: 番組のテーマ
- `topic: CuratedTopic`: 深掘り対象トピック（deep_diveのみ）
- `context: str`: 前セグメントの文脈要約
- `topic_titles: List[str]`: 全トピックのタイトル一覧（intro/conclusionのみ）

**出力**:
- `ScriptSegment`:
  - `segment_id: str`: セグメントID（例: "deep_dive_1"）
  - `segment_type: str`: セグメント種別
  - `turns: List[dict]`: DialogueTurn互換の対話ターン
  - `context_summary: str`: 次セグメント生成用の文脈要約（200〜300文字）

**使用モデル**: `gemini-3.1-pro-preview`（または `config.yaml > orchestrator.segment_model`）

**プロンプト**:
- `config/prompts.yaml > orchestrator.segment_intro`
- `config/prompts.yaml > orchestrator.segment_deep_dive`
- `config/prompts.yaml > orchestrator.segment_conclusion`

**ターン数設定**:
```yaml
orchestrator:
  intro:
    min_turns: 10
    max_turns: 20
  deep_dive:
    min_turns: 25
    max_turns: 45
  conclusion:
    min_turns: 10
    max_turns: 20
```

---

### 3.3 ScriptOrchestrator

**責務**: 全体統括・文脈管理・セグメント統合

**処理ステップ**:

1. **Step 1: TopicCurator でキュレーション**
   - リサーチデータ → CuratedTopic × N
   - 進捗: 50% → 52%

2. **Step 2: SegmentGenerator で順次生成**
   - intro → deep_dive_1 → ... → conclusion
   - 各セグメントの `context_summary` を次セグメントに引き継ぎ
   - 進捗: 52% → 63%

3. **Step 3: 統合**
   - 全セグメントの `turns` を結合
   - `DialogueTurn` への変換（speaker_id → speaker の後方互換処理）
   - 進捗: 63% → 65%

**エラーハンドリング**:
- セグメント単位で最大2回リトライ
- 接続エラー時は指数バックオフ（1秒 → 2秒）
- 部分失敗時も可能な限り統合を試みる
- **JSONパースエラー対策**（v3.5.0で強化）:
  - `max_output_tokens` を十分に確保（TopicCurator: 8192, MetadataGenerator: 4096）
  - `response_mime_type: "application/json"` を使用しない（JSON切断の原因となるため）
  - `finish_reason=MAX_TOKENS` を検出して警告
  - 4段階のサニタイズ処理（コードブロック除去、JSON抽出、制御文字除去、空白除去）
  - エラー時は完全な生レスポンステキストをログ出力（デバッグ用）
  - MetadataGeneratorはnon-fatalでフォールバック動作

**進捗フィードバック**:
```python
progress_callback.progress(0.50, "🔍 面白いトピックを選定中...")
progress_callback.progress(0.52, "📝 導入部を生成中...")
progress_callback.progress(0.55, "📝 深掘り「〇〇」生成中...")
progress_callback.progress(0.65, "✅ 台本生成完了（120ターン）")
```

---

## 4. データモデル

### 4.1 CuratedTopic

```python
class CuratedTopic(BaseModel):
    title: str                    # トピックタイトル
    content: str                  # 詳細情報（500〜800文字）
    priority: int                 # 優先度（1が最高）
    estimated_turns: int = 30     # 推定ターン数
    tone: str = "議論"            # 推奨トーン
    key_facts: List[str] = []     # 最重要ファクト
```

### 4.2 ScriptSegment

```python
class ScriptSegment(BaseModel):
    segment_id: str                           # 例: "deep_dive_1"
    segment_type: Literal["intro", "deep_dive", "conclusion"]
    topic_title: Optional[str] = None         # 深掘りトピックのタイトル
    turns: List[dict]                         # DialogueTurn互換
    context_summary: str = ""                 # 次セグメント用文脈要約
    token_count: int = 0                      # 出力トークン数
```

### 4.3 CurationResult

```python
class CurationResult(BaseModel):
    topics: List[CuratedTopic]    # 選定されたトピック
    curator_reasoning: str = ""   # 選定理由（デバッグ用）
```

---

## 5. 設定ファイル

### 5.1 config.yaml

```yaml
script_generator:
  orchestrator:
    enabled: false                # true: 新アーキテクチャ / false: 旧アーキテクチャ
    curator_model: "gemini-2.5-flash"
    segment_model: ""             # 空=script_generator.gemini.modelを使用
    max_topics: 3
    context_summary_max_length: 300
    intro:
      min_turns: 10
      max_turns: 20
    deep_dive:
      min_turns: 25
      max_turns: 45
    conclusion:
      min_turns: 10
      max_turns: 20
```

### 5.2 config/prompts.yaml

```yaml
orchestrator:
  curation: |
    あなたはラジオ番組のチーフリサーチャーです。
    膨大なリサーチデータを分析し、「ずんだもんとめたんが深く語り合うべきトピック」を厳選してください。
    ...

  segment_intro: |
    あなたは人気ラジオ番組の構成作家です。今日の番組の「導入部」を作成してください。
    ...

  segment_deep_dive: |
    あなたは人気ラジオ番組の構成作家です。選ばれた1つのトピックについて「深掘りセグメント」を作成してください。
    ...

  segment_conclusion: |
    あなたは人気ラジオ番組の構成作家です。今日の番組の「まとめとエンディング」を作成してください。
    ...
```

---

## 6. 使い方

### 6.1 有効化

`config.yaml` の1行を変更：

```yaml
orchestrator:
  enabled: true  # ← false から true に変更
```

### 6.2 無効化（旧アーキテクチャに戻す）

```yaml
orchestrator:
  enabled: false  # ← デフォルト
```

### 6.3 実行例

```python
from workflow import execute_scripting_phase
from core.models import load_config

config = load_config()
result = await execute_scripting_phase(
    theme="血糖値管理の最新技術",
    mode=ResearchMode.DEBATE,
    queries=["CGMの精度", "インスリンポンプの進化"],
    config=config,
    output_dir=Path("output/20260322_001"),
    enable_research=True,
    provider="gemini",
)
# → orchestrator.enabled=true の場合、ScriptOrchestrator が起動
```

---

## 7. 成功基準（Phase 6 検証用）

1. **深掘り**: 具体的なエピソード・数値データの言及が旧アーキテクチャの2倍以上
2. **JSON安定性**: 100回生成でJSONパースエラー0件
3. **文脈連続性**: 人間評価で「会話の流れが自然」が80%以上
4. **スケーラビリティ**: 150ターン超の台本を安定生成
5. **UX**: ユーザーアンケートで「進捗がわかりやすい」が80%以上

---

## 8. 今後の拡張可能性

- **並列生成**: 複数の deep_dive セグメントを並列API呼び出しで高速化
- **キャッシュ**: 同一リサーチデータのキュレーション結果をキャッシュ
- **動的セグメント数**: リサーチデータ量に応じてトピック数を自動調整
- **文脈要約の自動生成**: LLMで前セグメントの要約を生成（現在は各セグメントが自己生成）
- **マルチプロバイダー対応**: OpenAI/Anthropic でもオーケストレーターを使用可能に

---

## 9. 参考資料

- **現状分析**: `docs/script_generation_current_state.md`
- **設計プラン**: `.windsurf/plans/long-form-script-architecture-c91b14.md`
- **実装コード**:
  - `core/models/curation.py`
  - `core/interfaces/script_orchestrator.py`
  - `services/script_generation/topic_curator.py`
  - `services/script_generation/segment_generator.py`
  - `services/script_generation/orchestrator.py`
  - `workflow.py` (L711-L733: フィーチャーフラグ統合)
