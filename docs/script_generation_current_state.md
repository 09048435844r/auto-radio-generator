# 台本生成パイプライン - 現状分析ドキュメント

**作成日**: 2026年3月22日  
**対象バージョン**: v3.3.2  
**目的**: 超・高密度リサーチデータを消化し、長尺で面白い台本を生成するアーキテクチャへの改修準備

---

## 1. 処理フローの全体像

### 1.1 コールグラフ（関数呼び出し順序）

```
workflow.py::execute_scripting_phase()
  │
  ├─ [Step 1: リサーチ] (条件: enable_research=True かつ preloaded_research_data=None)
  │   └─ PerplexityResearcher.research_multi(queries, mode, avoid_topics)
  │       → ResearchResult (content: str, sources: list, usage: PerplexityUsage)
  │
  └─ [Step 2: 台本生成]
      ├─ create_script_generator(config, provider) → IScriptGenerator実装
      │   └─ GeminiClient / OpenAIClient / AnthropicClient のいずれか
      │
      └─ script_generator.generate(theme, research_data, avoid_topics, excluded_topics)
          │
          ├─ _build_user_prompt() → ユーザープロンプト構築
          │   ├─ テーマ
          │   ├─ リサーチ結果 (research_data.content) ← **ここに数千文字のMarkdownが流し込まれる**
          │   ├─ 参考リンク候補 (research_data.sources)
          │   ├─ excluded_topics (第2部モード用)
          │   └─ avoid_topics (Negative Prompt)
          │
          ├─ PromptManager.get_script_prompt() → システムプロンプト取得
          │   └─ config/prompts.yaml から読み込み
          │
          ├─ _call_api(system_prompt, user_prompt, use_schema=True)
          │   ├─ リトライ処理 (最大2回、指数バックオフ)
          │   ├─ Gemini API呼び出し (response_schema=Script)
          │   └─ finish_reason チェック (MAX_TOKENS, SAFETY, RECITATION)
          │
          └─ _parse_response(response_text) → Script オブジェクト
              ├─ json.loads() でJSONパース
              ├─ Pydantic Script(**json_data) でバリデーション
              └─ エラー時: _sanitize_json_response() → 再パース試行
```

### 1.2 現在の実装方式

- **1回のAPI呼び出しで全体を生成**: 現在、台本全体（導入〜深掘り〜まとめ）を **単一のAPI呼び出し** で生成している。
- **分割（チャンキング）なし**: リサーチデータの長さに関わらず、全文をプロンプトに流し込む方式。
- **第2部モード**: `excluded_topics`が指定された場合のみ、第1部の内容を前提知識として追加する特殊モード。

---

## 2. 現在のプロンプトの内容（最重要）

### 2.1 システムプロンプト

システムプロンプトは `config/prompts.yaml` の `script.standard` から取得される。

#### **主要な指示内容**:

```yaml
あなたは人気ラジオ番組の構成作家です。
リサーチ結果に基づき、以下の【構成ルール】に厳密に従って台本を作成してください。

## キャラクター設定
- ずんだもん: 好奇心旺盛だが少し生意気。ボケ役。
- めたん: 冷静で博識。ツッコミ兼解説役。

## 構成指示
1. 【導入】: 視聴者の常識を揺さぶる「問い」から始める。
2. 【深掘り】: リサーチ結果から、最も意外性のある「具体的エピソード」や「実験データ」を2つ選ぶ。
   - ⚠ 要約厳禁。そのエピソードの「いつ・誰が・どうした」というディテールを、情景が浮かぶように詳しく描写する。
3. 【結び】: 学びを抽象化してまとめる。

## 【重要】構成ルール（以下の3部構成で進行すること）

### 第1部：導入と全体像（全体の15%）
- テーマの提示と、リサーチ結果から分かる「結論」を最初に短く要約して伝える。
- 視聴者の興味を惹く「フック（問いかけ）」を行う。

### 第2部：深掘りトーク（全体の70%）★最重要
- リサーチ結果の中から、**特に面白い具体的なエピソード、数値データ、事例を2〜3個ピックアップ**する。
- ⚠ ここは絶対に要約しないこと。選んだトピックについて、具体的な数字や情景描写を交えて、ずんだもんとめたんに深く語らせる。
- 「広く浅く」ではなく「狭く深く」掘り下げる。

### 第3部：まとめとオチ（全体の15%）
- 今日の話を抽象化してまとめる。
- 最後はしっかりとしたオチ（コミカルな掛け合い）で終わる。

## 禁止事項
- リサーチ結果のすべてを網羅しようとすること（ダイジェスト化の禁止）。
- 教科書のような説明口調。あくまで「会話」として成立させること。
```

#### **口調のルール**:
- ずんだもん: 「〜なのだ」「〜だよ」「〜なんだね」
- めたん: 「〜ですね」「〜ですよ」「〜ですから」

#### **第2部モード専用の強化システムプロンプト**:
`excluded_topics`が指定された場合、以下の追加指示が適用される:

```
【重要】第1部で放送済みの全内容がユーザープロンプトで提供されます。これを以下のルールで徹底的に活用してください：

1. 【前提知識の活用】
   - 第1部で説明済みの内容は、既に視聴者が知っている前提知識として扱ってください
   - 同じ説明や定義を繰り返さず、その知識を土台としてさらに深掘りしてください

2. 【重複の物理的回避】
   - 第1部で使われた具体的な例え、データ、フレーズは絶対に再利用しないでください
   - 同じトピックを扱う場合でも、全く異なる角度、別の視点、新しい情報を提供してください

3. 【一貫性の維持】
   - 第1部で確立した定義や世界観と矛盾しない、一貫性のある言い回しを徹底してください
   - キャラクターの口調や人格設定は第1部から継続してください
```

### 2.2 ユーザープロンプト

`GeminiClient._build_user_prompt()` で構築される。

#### **構造**:

```python
## テーマ
{theme}

## リサーチ結果（{research_data.mode}モード）
{research_data.content}  # ← ★ここに数千文字のMarkdownが流し込まれる★

## <参考リンク候補>
以下のリンク候補の中から、台本の内容に最も関連が深く、視聴者に有益なものを厳選してください。

1. {source.title}: {source.url}
2. ...

[PART 1 CONTEXT - 第2部モード]  # excluded_topicsがある場合のみ
以下は第1部で放送済みの全内容です。第2部ではこれを前提知識として扱い、
重複説明を避け、新しい視点からの深掘りや別の側面に焦点を当ててください。

{excluded_topics}  # ← 第1部の台本全文（数千文字）

【重要制約】
- 第1部で説明済みの内容は、前提知識として簡潔に扱うか、全く異なる角度から深掘りしてください
- 第1部で使われた特定のフレーズや定義と矛盾しない、一貫性のある言い回しを徹底してください
- 可能であれば第1部の内容に軽く触れる（コールバックする）ことで、番組としての連続性を演出してください
- 物理的な重複（同じ説明、同じ例え、同じデータ）は絶対に避けてください

[NEGATIVE CONSTRAINTS]  # avoid_topicsがある場合のみ
The user has explicitly requested to AVOID the following topics/keywords in this script:
"{avoid_topics}"

STRICTLY FOLLOW this instruction. Do not mention, discuss, or allude to these topics.
Focus on other aspects of the theme to ensure variety.

上記の情報を基に、ラジオ台本をJSON形式で作成してください。
```

### 2.3 JSON出力スキーマ（Pydanticモデル）

`core/models/script.py` の `Script` クラスが使用される。

```python
class Script(BaseModel):
    title: str = ""  # 動画タイトル（後工程で生成）
    thumbnail_title: str = ""  # サムネイル用タイトル（後工程で生成）
    description: str = ""  # 概要欄（後工程で生成）
    hashtags: list[str] = []  # ハッシュタグ（5個前後）
    references: list[str] = []  # 参考URL（3〜5件）
    dialogue: list[DialogueTurn]  # 対話ターンのリスト
    
    @property
    def sections(self) -> list[DialogueTurn]:
        return self.dialogue  # 後方互換性のため
```

```python
class DialogueTurn(BaseModel):
    speaker: Literal["A", "B"]  # A=ずんだもん, B=めたん
    text: str  # セリフ本文
```

#### **スキーマ強制の仕組み**:
- `response_schema=Script` を `GenerateContentConfig` に渡すことで、Gemini APIが **構造化JSON出力** を強制する。
- これにより、JSON形式の不正や途切れが大幅に減少する。

---

## 3. APIパラメータと使用モデル

### 3.1 Gemini API設定（`config.yaml`）

```yaml
script_generator:
  gemini:
    model: "gemini-3.1-pro-preview"  # メインモデル（高品質・最新）
    fallback_model: "gemini-2.5-pro"  # フォールバックモデル（高速）
    max_tokens: 16384  # 最大トークン数（台本の長さ）
```

### 3.2 実際のAPI呼び出しパラメータ（`GeminiClient._call_api()`）

```python
config_params = {
    "max_output_tokens": 16384,  # 長文台本での途切れ防止のため固定値に設定
    "temperature": 0.7 if is_part2 else 0.85,  # 第2部モードでは低め
    "response_mime_type": "application/json",  # JSONモード有効化
    "safety_settings": [
        # すべてのカテゴリで BLOCK_NONE（医療系ワード等での誤爆防止）
        SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
    ],
    "response_schema": Script  # Pydanticモデルでスキーマ強制
}
```

### 3.3 トークン制限の考慮

- **入力トークン**: 制限なし（Gemini 1.5/2.0系は128K〜2Mトークンのコンテキストウィンドウ）
- **出力トークン**: `max_output_tokens=16384` で固定
  - 台本の平均的な長さは **5000〜8000トークン** 程度
  - 16384トークンは **約12,000〜16,000文字** に相当（日本語の場合）

---

## 4. 現状のエラーハンドリングと課題分析

### 4.1 現在のエラーハンドリング

#### **4.1.1 リトライ処理**

`GeminiClient._call_api()` で実装されている:

```python
max_retries = 2
for attempt in range(max_retries):
    try:
        response = self.client.models.generate_content(...)
        break  # 成功したらループを抜ける
    except Exception as e:
        error_msg = str(e).lower()
        if ("disconnected" in error_msg or "timeout" in error_msg or "connection" in error_msg) 
           and attempt < max_retries - 1:
            wait_time = 2 ** attempt  # 指数バックオフ: 1秒, 2秒
            console.print(f"接続エラー ({attempt + 1}/{max_retries})。{wait_time}秒後にリトライします...")
            time.sleep(wait_time)
            continue
        else:
            raise  # リトライ上限または回復不可能なエラー
```

- **対象エラー**: 接続エラー、タイムアウト、切断
- **リトライ回数**: 最大2回（初回 + 1回リトライ）
- **バックオフ**: 指数バックオフ（1秒 → 2秒）

#### **4.1.2 finish_reason チェック**

API呼び出し後、`finish_reason` をログ出力して途切れの原因を特定:

```python
finish_reason = candidate.finish_reason
if finish_reason in ['MAX_TOKENS', 'SAFETY', 'RECITATION']:
    logger.warning(f"出力が途中で終了した可能性: {finish_reason}")
    if finish_reason == 'MAX_TOKENS':
        logger.warning("max_output_tokens上限到達。出力が切り詰められました。")
    elif finish_reason == 'SAFETY':
        logger.warning("セーフティフィルターが発動。特定のワードが原因の可能性があります。")
    elif finish_reason == 'RECITATION':
        logger.warning("著作権保護により出力が遮断されました。")
```

- **MAX_TOKENS**: 出力トークン上限（16384）に到達
- **SAFETY**: セーフティフィルター発動
- **RECITATION**: 著作権保護による遮断

#### **4.1.3 JSONパースエラー時の処理**

`GeminiClient._parse_response()` で実装:

```python
try:
    json_data = json.loads(response_text.strip(), strict=False)
    script_obj = Script(**json_data)  # Pydanticバリデーション
    return script_obj
except json.JSONDecodeError as e:
    console.print(f"JSON解析エラー、サニタイズ再試行: {e}")
    sanitized_text = self._sanitize_json_response(response_text)
    
    try:
        json_data = json.loads(sanitized_text, strict=False)
        script_obj = Script(**json_data)
        return script_obj
    except Exception as retry_error:
        console.print(f"サニタイズ後も解析失敗: {retry_error}")
        raise
```

- **第1段階**: 通常のJSONパース + Pydanticバリデーション
- **第2段階**: `_sanitize_json_response()` でサニタイズ → 再パース
- **失敗時**: 例外を上位に伝播（ワークフロー中断）

#### **4.1.4 フォールバックモデル**

`GeminiClient.generate()` でメインモデル失敗時にフォールバックモデルで再試行:

```python
except Exception as e:
    console.print(f"Gemini API エラー: {e}")
    if self.model_name != self.fallback_model:
        console.print(f"フォールバックモデル {self.fallback_model} で再試行...")
        original_model = self.model_name
        self.model_name = self.fallback_model
        try:
            response_text, usage = self._call_api(system_prompt, user_prompt, use_schema=True)
            script = self._parse_response(response_text)
            return script
        finally:
            self.model_name = original_model
    raise
```

### 4.2 数千文字の超・高密度リサーチデータ投入時の予想される問題

#### **問題1: 情報過多による「ダイジェスト化」の誘発**

**現象**:
- システムプロンプトは「リサーチ結果のすべてを網羅しようとすること（ダイジェスト化の禁止）」を明示している。
- しかし、リサーチデータが **3000〜5000文字** を超えると、LLMは「全体を要約しなければ」というプレッシャーを感じやすい。

**結果**:
- 「広く浅く」の台本になり、「狭く深く」の指示が守られない。
- 具体的なエピソードや数値データが省略され、抽象的な説明に終始する。

**根本原因**:
- プロンプトの指示（「2〜3個ピックアップ」）と、リサーチデータの物量（数千文字）のギャップ。
- LLMは「提供された情報を無駄にしてはいけない」というバイアスを持つため、全体を網羅しようとする傾向がある。

#### **問題2: JSONの途切れ（MAX_TOKENS）**

**現象**:
- リサーチデータが長いと、入力トークン数が増加する。
- 入力トークンが多いと、LLMは出力トークンの予算を圧迫される可能性がある（内部的な最適化）。
- 結果として、`max_output_tokens=16384` に到達する前に、LLMが出力を打ち切る可能性がある。

**結果**:
- JSON出力が途中で途切れ、`json.JSONDecodeError` が発生。
- `_sanitize_json_response()` でも修復できない場合、ワークフロー全体が失敗する。

**根本原因**:
- Gemini APIの内部的なトークン配分アルゴリズム。
- `response_schema` による構造化出力は途切れを **減少** させるが、**完全に防ぐ** わけではない。

#### **問題3: プロンプトの複雑化によるコンテキスト理解の低下**

**現象**:
- ユーザープロンプトに以下が含まれる:
  - テーマ（数十文字）
  - リサーチ結果（**3000〜5000文字**）
  - 参考リンク候補（数百文字）
  - excluded_topics（第2部モードの場合、**さらに数千文字**）
  - avoid_topics（数十〜数百文字）
- 合計で **5000〜10000文字** 以上のプロンプトになる。

**結果**:
- LLMが「どの情報が最も重要か」を判断しにくくなる。
- システムプロンプトの指示（「2〜3個ピックアップ」）が埋もれ、実行されない。

**根本原因**:
- プロンプトの構造が「フラット」で、情報の優先順位が不明確。
- LLMは「すべての情報を平等に扱う」傾向があるため、重要な指示が希釈される。

#### **問題4: 第2部モードでのコンテキスト爆発**

**現象**:
- 第2部モードでは、`excluded_topics` に第1部の台本全文（**3000〜5000文字**）が含まれる。
- リサーチデータ（**3000〜5000文字**）と合わせて、**6000〜10000文字** のコンテキストになる。

**結果**:
- LLMが「第1部との差別化」に注力しすぎて、リサーチデータの活用が疎かになる。
- または、第1部の内容を「前提知識」として扱わず、再度説明してしまう（重複）。

**根本原因**:
- 第2部モードのシステムプロンプトが「重複回避」を強調しすぎている。
- LLMは「何をしてはいけないか」よりも「何をすべきか」の指示に従いやすい。

#### **問題5: トークン上限エラー（理論的には低リスク）**

**現象**:
- Gemini 1.5/2.0系のコンテキストウィンドウは **128K〜2Mトークン** と非常に大きい。
- しかし、入力トークンが **50K〜100K** を超えると、APIのレスポンス時間が大幅に増加する可能性がある。

**結果**:
- タイムアウトエラー（リトライ処理で対応可能）。
- または、APIの内部的な最適化により、出力品質が低下する可能性。

**根本原因**:
- LLMの注意機構（Attention）は、コンテキストが長いほど計算コストが増加する（O(n²)）。

---

## 5. 考察と推奨される改修方針

### 5.1 現状の強み

1. **構造化出力の強制**: `response_schema=Script` により、JSON形式の不正が大幅に減少。
2. **リトライ処理**: 接続エラーに対する自動リトライが実装済み。
3. **finish_reason チェック**: 途切れの原因を特定できる仕組みがある。
4. **フォールバックモデル**: メインモデル失敗時の代替手段がある。

### 5.2 現状の弱点

1. **情報の選別がLLM任せ**: リサーチデータの中から「2〜3個ピックアップ」する判断を、LLMに丸投げしている。
2. **プロンプトの構造が不明確**: 情報の優先順位が視覚的に分かりにくい。
3. **単一API呼び出しの限界**: 長文生成において、途切れのリスクがゼロではない。
4. **第2部モードの複雑性**: `excluded_topics` の扱いが難しく、重複回避と情報活用のバランスが取りにくい。

### 5.3 推奨される改修方針（次ステップ）

#### **方針1: リサーチデータの事前要約・構造化**

- **目的**: LLMに渡す前に、リサーチデータを「台本生成に最適な形」に加工する。
- **実装案**:
  1. リサーチデータ（3000〜5000文字）を、軽量モデル（`gemini-2.5-flash`）で **要約** する。
  2. 要約時に「具体的なエピソード」「数値データ」「専門家の見解」を **抽出** し、構造化する。
  3. 構造化されたデータ（1000〜1500文字）を台本生成プロンプトに流し込む。

#### **方針2: プロンプトの階層化・優先順位の明示**

- **目的**: LLMが「何を最優先すべきか」を明確に理解できるようにする。
- **実装案**:
  1. ユーザープロンプトを **セクション分け** する（例: `## 最重要指示`, `## 参考情報`, `## 制約条件`）。
  2. 「2〜3個ピックアップ」の指示を **最上部** に配置する。
  3. リサーチデータは「参考情報」として、優先度を下げる。

#### **方針3: 台本生成の段階的実行（チャンキング）**

- **目的**: 長文生成のリスクを分散し、途切れを防ぐ。
- **実装案**:
  1. **第1段階**: 「導入部」のみを生成（15%）。
  2. **第2段階**: 「深掘りトーク」のみを生成（70%）。
  3. **第3段階**: 「まとめとオチ」のみを生成（15%）。
  4. 最後に3つを結合して、完全な台本を構築する。

#### **方針4: 第2部モードの簡素化**

- **目的**: `excluded_topics` の扱いを簡素化し、LLMの負担を減らす。
- **実装案**:
  1. 第1部の台本全文ではなく、**キーワードリスト** のみを抽出する。
  2. 「第1部で使われたキーワード: A, B, C」という形で、簡潔に伝える。
  3. 重複回避の指示を「ネガティブ」から「ポジティブ」に変換（例: 「新しい視点を提供してください」）。

#### **方針5: 出力トークン数の動的調整**

- **目的**: リサーチデータの長さに応じて、`max_output_tokens` を調整する。
- **実装案**:
  1. リサーチデータが3000文字以上の場合、`max_output_tokens` を **20000** に増やす。
  2. リサーチデータが1500文字以下の場合、`max_output_tokens` を **12000** に減らす（コスト削減）。

---

## 6. まとめ

### 6.1 現状の台本生成パイプラインの特徴

- **単一API呼び出し**: リサーチデータ全文を一度に流し込み、台本全体を生成。
- **構造化出力**: `response_schema=Script` により、JSON形式の安定性が高い。
- **リトライ処理**: 接続エラーに対する自動リトライが実装済み。

### 6.2 超・高密度リサーチデータ投入時の主要リスク

1. **情報過多による「ダイジェスト化」**: LLMが全体を要約しようとし、「狭く深く」の指示が守られない。
2. **JSONの途切れ**: 入力トークンが多いと、出力トークンの予算が圧迫され、途切れのリスクが増加。
3. **プロンプトの複雑化**: 情報の優先順位が不明確になり、重要な指示が埋もれる。
4. **第2部モードのコンテキスト爆発**: `excluded_topics` により、コンテキストが6000〜10000文字に達する。

### 6.3 次ステップの推奨事項

1. **リサーチデータの事前要約・構造化**: 軽量モデルで要約し、台本生成に最適な形に加工。
2. **プロンプトの階層化**: 情報の優先順位を明示し、LLMの理解を助ける。
3. **台本生成の段階的実行**: 導入・深掘り・まとめを分割生成し、途切れリスクを分散。
4. **第2部モードの簡素化**: `excluded_topics` をキーワードリストに変換し、負担を軽減。
5. **出力トークン数の動的調整**: リサーチデータの長さに応じて、`max_output_tokens` を調整。

---

**次のアクション**: 上記の改修方針を基に、具体的な実装計画を策定し、段階的にアーキテクチャを改善していく。
