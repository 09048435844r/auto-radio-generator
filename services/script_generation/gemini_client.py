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
from core.prompt_manager import PromptManager
from .time_expressions import get_time_expression

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
        self.prompt_manager = PromptManager()
        
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
            
            # フォールバックモデルで再試行
            if self.fallback_model and self.fallback_model != self.model_name:
                console.print(f"[yellow]フォールバックモデルで再試行: {self.fallback_model}[/yellow]")
                original_model = self.model_name
                try:
                    self.model_name = self.fallback_model
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
                    
                    console.print(f"[green]✓ フォールバックモデルで検索計画作成完了[/green]")
                    console.print(f"  切り口: {plan.angle}")
                    console.print(f"  クエリ数: {len(plan.queries)}")
                    
                    return plan
                    
                finally:
                    self.model_name = original_model
            
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
        
        # モード別に専用プロンプトを使用（PromptManagerから取得）
        if research_data and research_data.mode == "weekly_digest":
            # 時間表現を取得
            time_expr = get_time_expression("weekly_digest")
            system_prompt = self.prompt_manager.get_script_prompt(
                "weekly_digest",
                title_prefix=time_expr["title_prefix"],
                intro_phrase=time_expr["intro_phrase"],
                outro_phrase=time_expr["outro_phrase"],
                theme=theme,
                main_char=self.personalities.main,
                sub_char=self.personalities.sub
            )
        elif research_data and research_data.mode == "lecture":
            system_prompt = self.prompt_manager.get_script_prompt(
                "lecture",
                theme=theme,
                main_char=self.personalities.main,
                sub_char=self.personalities.sub
            )
        else:
            system_prompt = self.prompt_manager.get_script_prompt(
                "standard",
                main_char=self.personalities.main,
                sub_char=self.personalities.sub,
                main_topic_ratio=self.structure.main_topic_ratio,
                listener_mail_ratio=self.structure.listener_mail_ratio,
                ending_ratio=self.structure.ending_ratio
            )
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
            
            "weekly_digest": """1. **最近の出来事**: 直近1ヶ月以内のニュースや動向を探るクエリ（「最近」「最新」など広義の言葉を使用）
   - 例: "○○ ニュース 最近", "○○ latest news 1 month", "○○ 最新動向 2024"
   - 注意: 「今週」「this week」などの厳密な期間指定は避ける（ニュースが見つからない可能性があるため）

2. **世間の反応**: SNSや世論の最近の反応を探るクエリ
   - 例: "○○ 最近の反応", "○○ 最新の評判", "○○ SNS 話題"

3. **今後の展望**: 最近発表された予測や今後の動きを探るクエリ
   - 例: "○○ 今後の予測", "○○ 最新の見通し", "○○ 将来性""",
            
            "voices": """1. **口コミ・評判**: 実際の利用者の声や評価を探るクエリ
   - 例: "○○ 口コミ", "○○ 評判"

2. **体験談**: 実際の体験や事例を探るクエリ
   - 例: "○○ 体験談", "○○ 使ってみた"

3. **街の声**: SNSやフォーラムでの反応を探るクエリ
   - 例: "○○ SNS反応", "○○ みんなの意見""",
            
            "lecture": """1. **基本定義**: 初心者向けの分かりやすい説明を探るクエリ（専門用語を避ける）
   - 例: "○○ とは 初心者向け わかりやすく", "○○ 簡単に説明"

2. **仕組み・構造**: 図解や比喩を使った説明を探るクエリ
   - 例: "○○ 仕組み 図解 例え話", "○○ どういう仕組み 分かりやすく"

3. **メリット・活用例**: 何ができるか、どう役立つかを探るクエリ
   - 例: "○○ メリット 何ができる", "○○ 5歳児でもわかる", "○○ 具体例"""
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

    def generate_packaging_prompt(self, theme: str, script_summary: str) -> str:
        """packagingプロンプトを使用してメタデータを生成
        
        Args:
            theme: テーマ
            script_summary: 台本の要約
            
        Returns:
            生成されたメタデータJSON文字列
        """
        # プロンプトマネージャーからpackagingプロンプトを取得
        packaging_prompt = self.prompt_manager.get_prompt("packaging", "default")
        
        # 変数を置換
        formatted_prompt = packaging_prompt.format(
            theme=theme,
            script_summary=script_summary
        )
        
        # Geminiで生成（_call_apiメソッドを使用）
        response_text, _ = self._call_api(
            system_prompt="",
            user_prompt=formatted_prompt
        )
        return response_text
    
