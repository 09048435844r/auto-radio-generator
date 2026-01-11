"""Gemini APIを使用した台本生成クライアント"""
import json
import re
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.interfaces import IScriptGenerator, ResearchResult
from core.models import Script, DialogueLine, AppConfig, GeminiUsage, ResearchPlan

console = Console()


class GeminiClient(IScriptGenerator):
    """Google Gemini APIを使用した台本生成
    
    リサーチデータを基に、3部構成のラジオ台本を生成する。
    - Part 1 (70%): 本題 - リサーチ結果を基にした議論
    - Part 2 (20%): リスナーメールコーナー - 架空の質問と回答
    - Part 3 (10%): エンディング - 締めの挨拶
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        
        api_key = config.env.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません")
        
        self.client = genai.Client(api_key=api_key)
        
        self.model_name = config.yaml.script_generator.gemini.model
        self.fallback_model = config.yaml.script_generator.gemini.fallback_model
        self.max_tokens = config.yaml.script_generator.gemini.max_tokens
        self.structure = config.yaml.script_generator.structure
        self.personalities = config.yaml.personalities
        
        # 最後のAPI呼び出しの使用量を保持
        self.last_usage: GeminiUsage | None = None
    
    async def create_research_plan(self, theme: str, mode: str, instruction: str | None = None) -> ResearchPlan:
        """AIプロデューサー: テーマから検索計画を作成
        
        Args:
            theme: 動画のテーマ
            mode: リサーチモード (trivia/debate/weekly_digest/voices)
            instruction: ユーザーからの追加指示（オプション）
        
        Returns:
            ResearchPlan: 検索クエリと台本の切り口
        """
        console.print(f"[cyan]AIプロデューサー: 検索計画を作成中...[/cyan]")
        console.print(f"  テーマ: {theme}")
        console.print(f"  モード: {mode}")
        if instruction:
            console.print(f"  追加指示: {instruction}")
        
        system_prompt = self._build_research_plan_prompt(mode)
        user_prompt = f"## テーマ\n{theme}\n\n"
        
        if instruction:
            user_prompt += f"## 追加指示\n{instruction}\n\n"
        
        user_prompt += "上記のテーマについて、検索計画をJSON形式で作成してください。"
        
        try:
            response_text, usage = self._call_api(system_prompt, user_prompt)
            self.last_usage = usage
            
            # JSONを抽出してパース
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text.strip()
            
            data = json.loads(json_str)
            plan = ResearchPlan(
                queries=data.get("queries", []),
                angle=data.get("angle", "")
            )
            
            console.print(f"[green]✓ 検索計画作成完了[/green]")
            console.print(f"  切り口: {plan.angle}")
            console.print(f"  クエリ数: {len(plan.queries)}")
            
            return plan
            
        except Exception as e:
            console.print(f"[red]✗ 検索計画作成エラー: {e}[/red]")
            raise
    
    def generate(self, theme: str, research_data: Optional[ResearchResult] = None) -> Script:
        """テーマとリサーチデータに基づいて台本を生成する
        
        Args:
            theme: 台本のテーマ
            research_data: リサーチ結果（オプション）
        
        Note:
            API使用量は self.last_usage で取得可能
        """
        console.print(f"[cyan]Gemini で台本を生成中...[/cyan]")
        console.print(f"  テーマ: {theme}")
        console.print(f"  リサーチデータ: {'あり' if research_data else 'なし'}")
        
        # weekly_digestモードの場合は専用プロンプトを使用
        if research_data and research_data.mode == "weekly_digest":
            system_prompt = self._build_weekly_digest_prompt(theme)
        else:
            system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(theme, research_data)
        self.last_usage = None  # リセット
        
        try:
            response_text, usage = self._call_api(system_prompt, user_prompt)
            self.last_usage = usage
            script = self._parse_response(response_text)
            
            console.print(f"[green]✓ 台本生成完了[/green] 対話数: {len(script.dialogue)}")
            if usage:
                console.print(f"  トークン: 入力 {usage.input_tokens:,} / 出力 {usage.output_tokens:,}")
            return script
            
        except Exception as e:
            console.print(f"[red]✗ Gemini API エラー: {e}[/red]")
            # フォールバックモデルで再試行
            if self.model_name != self.fallback_model:
                console.print(f"[yellow]フォールバックモデル {self.fallback_model} で再試行...[/yellow]")
                original_model = self.model_name
                self.model_name = self.fallback_model
                try:
                    response_text, usage = self._call_api(system_prompt, user_prompt)
                    self.last_usage = usage
                    script = self._parse_response(response_text)
                    return script
                finally:
                    self.model_name = original_model
            raise
    
    def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, GeminiUsage]:
        """Gemini APIを呼び出す
        
        Returns:
            tuple[str, GeminiUsage]: (レスポンステキスト, 使用量)
        """
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{system_prompt}\n\n{user_prompt}")]
                )
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=self.max_tokens,
                temperature=0.85,
            )
        )
        
        # 使用量を取得
        usage = GeminiUsage(
            input_tokens=0,
            output_tokens=0,
            request_count=1,
            model_name=self.model_name
        )
        
        # usage_metadataからトークン数を取得
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            usage.input_tokens = getattr(meta, 'prompt_token_count', 0) or 0
            usage.output_tokens = getattr(meta, 'candidates_token_count', 0) or 0
        
        return response.text, usage
    
    def _build_user_prompt(self, theme: str, research_data: Optional[ResearchResult]) -> str:
        """ユーザープロンプトを構築"""
        prompt = f"## テーマ\n{theme}\n\n"
        
        if research_data:
            prompt += f"## リサーチ結果（{research_data.mode}モード）\n"
            prompt += f"{research_data.content}\n\n"
        
        prompt += "上記の情報を基に、ラジオ台本をJSON形式で作成してください。"
        return prompt
    
    def _parse_response(self, response_text: str) -> Script:
        """APIレスポンスからScriptオブジェクトを生成"""
        # JSONブロックを抽出
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # JSONブロックがない場合、全体をJSONとして解釈
            json_str = response_text.strip()
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            console.print(f"[yellow]JSON解析エラー、再解析を試みます...[/yellow]")
            # 余分な文字を削除して再試行
            json_str = re.sub(r'^[^{]*', '', json_str)
            json_str = re.sub(r'[^}]*$', '', json_str)
            data = json.loads(json_str)
        
        # Scriptオブジェクトに変換（sectionフィールドも含む）
        dialogue = [
            DialogueLine(
                speaker_id=line["speaker_id"],
                text=line["text"],
                section=line.get("section")  # セクションマーカー（オプション）
            )
            for line in data.get("dialogue", [])
        ]
        
        return Script(
            title=data.get("title", "無題"),
            description=data.get("description", ""),
            dialogue=dialogue
        )
    
    def _build_research_plan_prompt(self, mode: str) -> str:
        """検索計画作成用のシステムプロンプトを構築
        
        Args:
            mode: リサーチモード (trivia/debate/weekly_digest/voices)
        """
        base_prompt = """あなたはラジオ番組の構成作家です。
テーマを面白く深掘りするための「検索クエリ」を考案してください。

## タスク
テーマに対して、以下の3つの観点から検索クエリを作成してください：
"""
        
        # モード別の指示
        mode_instructions = {
            "trivia": """1. **意外な事実**: あまり知られていない数字や歴史的背景を探るクエリ
   - 例: "○○の意外な歴史", "○○にまつわる驚きの数字"

2. **雑学・トリビア**: 面白いエピソードや豆知識を探るクエリ
   - 例: "○○の面白いエピソード", "○○の豆知識"

3. **深掘り**: 一般には語られない裏話や詳細を探るクエリ
   - 例: "○○の裏側", "○○の詳しい仕組み""",
            
            "debate": """1. **賛成意見**: メリットや推進派の主張を探るクエリ
   - 例: "○○のメリット", "○○を支持する理由"

2. **反対意見**: デメリットや批判的な意見を探るクエリ
   - 例: "○○のデメリット", "○○に対する批判"

3. **対立軸**: 賛否両論や議論のポイントを探るクエリ
   - 例: "○○をめぐる議論", "○○の賛否両論""",
            
            "weekly_digest": """1. **今週の出来事**: 直近1週間の最新ニュースを探るクエリ（必ず「今週」「最新」を含める）
   - 例: "○○ 今週のニュース", "○○ 最新動向 2024"

2. **世間の反応**: SNSや世論の反応を探るクエリ（時事性重視）
   - 例: "○○ 今週の反応", "○○ 最新の評判"

3. **今後の展望**: 今週発表された予測や今後の動きを探るクエリ
   - 例: "○○ 今後の予測", "○○ 最新の見通し""",
            
            "voices": """1. **口コミ・評判**: 実際の利用者の声や評価を探るクエリ
   - 例: "○○ 口コミ", "○○ 評判"

2. **体験談**: 実際の体験や事例を探るクエリ
   - 例: "○○ 体験談", "○○ 使ってみた"

3. **街の声**: SNSやフォーラムでの反応を探るクエリ
   - 例: "○○ SNS反応", "○○ みんなの意見"""
        }
        
        mode_instruction = mode_instructions.get(mode, mode_instructions["trivia"])
        
        return base_prompt + mode_instruction + """

## 追加指示について
ユーザーから追加指示がある場合は、それを最優先してクエリを構成してください。

## 出力形式
以下のJSON形式で出力してください：

```json
{
  "queries": [
    "検索クエリ1",
    "検索クエリ2",
    "検索クエリ3"
  ],
  "angle": "今回の台本の切り口・コンセプト（1文で）"
}
```

## 注意事項
- クエリは具体的で検索しやすいものにする
- 各クエリは異なる観点から情報を集められるようにする
- angleは視聴者が興味を持つような切り口を提案する
"""
    
    def _build_system_prompt(self) -> str:
        """3部構成のラジオ台本生成用システムプロンプトを構築"""
        main_char = self.personalities.main
        sub_char = self.personalities.sub
        
        return f"""あなたは人気ラジオ番組の台本作家です。
2人のパーソナリティによる掛け合いトーク番組の台本を作成してください。

## パーソナリティ設定

### メインパーソナリティ（speaker_id: "main"）
- 名前: {main_char.name}
- 性格: {main_char.description}

### サブパーソナリティ（speaker_id: "sub"）
- 名前: {sub_char.name}
- 性格: {sub_char.description}

## 台本構成（厳守）

台本は以下の3部構成で作成してください：

### Part 1: 本題 ({self.structure.main_topic_ratio}%)
- **挨拶は一切不要**。いきなり本題から始める
- リサーチ結果を基に、2人で議論・解説を行う
- {main_char.name}が話題を振り、{sub_char.name}が補足・ツッコミを入れる
- 専門用語は噛み砕いて説明する

### Part 2: リスナーメールコーナー ({self.structure.listener_mail_ratio}%)
- 「さて、ここでリスナーからのお便りなのだ」のような導入
- 架空のリスナー（ラジオネーム付き）からの質問を作成
- テーマに関連した質問に2人で回答する

### Part 3: エンディング ({self.structure.ending_ratio}%)
- 簡潔な締めの挨拶
- 次回予告（任意）
- 「またね！」などの短い別れの挨拶

## タイトル生成の制約条件（厳守）

**禁止事項**:
1. タイトルやサムネイルテキストに「【今週のニュース】」「【特集】」「Vol.1」などのプレフィックス（接頭辞）を付けないこと
2. 「AIニュース」「ラジオ」などの一般的なチャンネル名や番組名をタイトルに入れないこと
3. 中身の具体的なトピックやベネフィット（利益）にフォーカスすること

**Few-Shot Examples（例示）**:
- ❌ Bad: 【健康】中性脂肪について解説
- ✅ Good: 中性脂肪は実は正義だった！？
- ❌ Bad: 今週の経済ニュースまとめ
- ✅ Good: 円安が止まらない本当の理由
- ❌ Bad: AIラジオ：最新技術動向
- ✅ Good: GPT-5はいつ来る？予測まとめ

## 出力形式（JSON）

必ず以下のJSON形式で出力してください：

```json
{{
  "title": "番組タイトル（上記の制約条件を厳守し、テーマを反映した魅力的なタイトル）",
  "thumbnail_title": "サムネイル用の短い釣りタイトル（10〜15文字以内のキャッチコピー。装飾なし。例: 「血糖値の新常識」「朝食の魔法」など）",
  "description": "番組の概要（YouTube説明文用、SEOを意識して関連キーワードを自然に盛り込み、動画の内容を興味深く詳細に要約すること。500文字程度を目安に）",
  "dialogue": [
    {{"speaker_id": "main", "text": "セリフ内容", "section": "intro"}},
    {{"speaker_id": "sub", "text": "セリフ内容"}},
    ...
    {{"speaker_id": "main", "text": "セリフ内容", "section": "main"}},
    ...
    {{"speaker_id": "main", "text": "セリフ内容", "section": "listener_mail"}},
    ...
    {{"speaker_id": "main", "text": "セリフ内容", "section": "ending"}},
    ...
  ]
}}
```

## セクションマーカー（重要）
各セクションの**最初のセリフ**にのみ `section` フィールドを付けてください：
- `"intro"` - オープニングの最初
- `"main"` - 本題の最初
- `"listener_mail"` - リスナーメールの最初
- `"ending"` - エンディングの最初

## 重要な注意事項
- 各セリフは1〜3文程度に収める（長すぎると聞きづらい）
- 相槌や笑い声も適度に入れる（例: 「へぇ〜」「なるほどなのだ」）
- 対話は40〜60ターン程度を目安に
- キャラクターの口調を厳守すること"""

    def _build_weekly_digest_prompt(self, theme: str) -> str:
        """今週のニュースまとめ専用のシステムプロンプトを構築
        
        ニュースキャスター＋コメンテーター形式の台本を生成する。
        リスナーメールコーナーは含めず、純粋なニュース解説に特化。
        """
        main_char = self.personalities.main
        sub_char = self.personalities.sub
        
        return f"""あなたは人気ニュース番組の台本作家です。
2人のキャスターによる「今週のニュースまとめ」番組の台本を作成してください。

## キャスター設定

### ニュースキャスター / 進行役（speaker_id: "main"）
- 名前: {main_char.name}
- 役割: ニュースの見出しと事実を読み上げ、議題を進行する
- 性格: {main_char.description}

### 専門コメンテーター / 解説役（speaker_id: "sub"）
- 名前: {sub_char.name}
- 役割: ニュースの背景や影響を深く解説する
- 性格: {sub_char.description}

## 番組構成（厳守）

### イントロ
- 「{theme}に関する今週のトップ3ニュースをお届けするのだ！」のような短い導入
- 挨拶は最小限に

### 本編: ニュース1, 2, 3 を順番に紹介
各ニュースについて：
1. **{main_char.name}（進行役）**: 見出しを読み上げ、事実（5W1H）を簡潔に伝える
2. **{sub_char.name}（解説役）**: 背景(Context)と影響(Impact)を深掘り解説
3. **{main_char.name}**: SNSや専門家の反応を紹介
4. 2人で短いやり取り（感想・補足）
5. 次のニュースへの移行

### アウトロ
- 今週のニュースを簡潔にまとめる
- 「来週もニュースチェックをお忘れなく！」のような締め

## 出力形式（JSON）

必ず以下のJSON形式で出力してください：

```json
{{
  "title": "【今週のまとめ】{theme}に関する重要ニュース3選",
  "description": "番組の概要（YouTube説明文用、SEOを意識して関連キーワードを自然に盛り込み、動画の内容を興味深く詳細に要約すること。500文字程度を目安に）",
  "dialogue": [
    {{"speaker_id": "main", "text": "セリフ内容", "section": "intro"}},
    {{"speaker_id": "sub", "text": "セリフ内容"}},
    ...
    {{"speaker_id": "main", "text": "ニュース1の見出し...", "section": "news_1"}},
    ...
    {{"speaker_id": "main", "text": "ニュース2の見出し...", "section": "news_2"}},
    ...
    {{"speaker_id": "main", "text": "ニュース3の見出し...", "section": "news_3"}},
    ...
    {{"speaker_id": "main", "text": "セリフ内容", "section": "ending"}},
    ...
  ]
}}
```

## セクションマーカー（重要）
各セクションの**最初のセリフ**にのみ `section` フィールドを付けてください：
- `"intro"` - オープニングの最初
- `"news_1"` - ニュース1の最初（見出しを読み上げるセリフ）
- `"news_2"` - ニュース2の最初
- `"news_3"` - ニュース3の最初
- `"ending"` - エンディングの最初

## 重要な注意事項
- 各セリフは1〜3文程度に収める
- ニュースの正確性を重視しつつ、分かりやすく伝える
- 専門用語は噌み砕いて説明する
- 対話は50〜70ターン程度を目安に
- キャラクターの口調を厳守すること"""
