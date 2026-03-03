"""Gemini APIを使用した台本生成クライアント"""
import json
import re
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.interfaces import IScriptGenerator, ResearchResult
from core.models import Script, AppConfig, GeminiUsage, ResearchPlan
from core.prompt_manager import PromptManager
from .time_expressions import get_time_expression
import logging

logger = logging.getLogger(__name__)

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
        
        # 実行ログ用: プロンプト記録リスト
        self.prompt_records: list = []
    
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
            response_text, usage = self._call_api(system_prompt, user_prompt, use_schema=False, phase="planning")
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
    
    def generate(self, theme: str, research_data: Optional[ResearchResult] = None, avoid_topics: Optional[str] = None, excluded_topics: Optional[str] = None) -> Script:
        """テーマとリサーチデータに基づいて台本を生成する
        
        Args:
            theme: 台本のテーマ
            research_data: リサーチ結果（オプション）
            avoid_topics: 避けてほしい話題（オプション）
            excluded_topics: 除外する話題（第2部モード用、オプション）
        
        Note:
            API使用量は self.last_usage で取得可能
        """
        
        # Mock Mode Check
        mock_mode = self.config.yaml.dev.mock_mode if hasattr(self.config.yaml, 'dev') else False
        if mock_mode:
            mock_data_path = self.config.yaml.dev.mock_data_path if hasattr(self.config.yaml.dev, 'mock_data_path') else "tests/mock_data"
            mock_file = Path(mock_data_path) / "script.json"
            
            if mock_file.exists():
                console.print(f"[yellow]⚠ MOCK MODE: Using data from {mock_file}[/yellow]")
                with open(mock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    script_obj = Script(**data)
                    # 使用量をリセット（Mockなので0）
                    self.last_usage = GeminiUsage(
                        input_tokens=0,
                        output_tokens=0,
                        request_count=0,
                        model_name="mock"
                    )
                    return script_obj
            else:
                console.print(f"[red]✗ Mock data not found at {mock_file}[/red]")
                console.print(f"[yellow]  Falling back to normal API execution...[/yellow]")
        
        console.print(f"[cyan]Gemini で台本を生成中...[/cyan]")
        console.print(f"  テーマ: {theme}")
        console.print(f"  リサーチデータ: {'あり' if research_data else 'なし'}")
        if excluded_topics:
            console.print(f"[INFO] 第2部モード: 第1部コンテキストを適用 ({len(excluded_topics)}文字)")
        
        # モード別に専用プロンプトを使用（PromptManagerから取得）
        # 第2部モード時は強化システムプロンプトを適用
        if excluded_topics and excluded_topics.strip():
            # 第2部モード専用の強化システムプロンプト
            system_prompt = self._build_part2_system_prompt()
        elif research_data and research_data.mode == "weekly_digest":
            # 時間表現を取得
            time_expr = get_time_expression("weekly_digest")
            system_prompt = self.prompt_manager.get_script_prompt(
                "weekly_digest",
                title_prefix=time_expr["title_prefix"],
                intro_phrase=time_expr["intro_phrase"],
                outro_phrase=time_expr["outro_phrase"],
                theme=theme,
                main_char=self.personalities.main,
                sub_char=self.personalities.sub,
                main=self.personalities.main,  # {main} 変数用
                sub=self.personalities.sub      # {sub} 変数用
            )
        elif research_data and research_data.mode == "lecture":
            system_prompt = self.prompt_manager.get_script_prompt(
                "lecture",
                theme=theme,
                main_char=self.personalities.main,
                sub_char=self.personalities.sub,
                main=self.personalities.main,  # {main} 変数用
                sub=self.personalities.sub      # {sub} 変数用
            )
        else:
            system_prompt = self.prompt_manager.get_script_prompt(
                "standard",
                main_char=self.personalities.main,
                sub_char=self.personalities.sub,
                main=self.personalities.main,  # {main} 変数用
                sub=self.personalities.sub,     # {sub} 変数用
                main_topic_ratio=self.structure.main_topic_ratio,
                listener_mail_ratio=self.structure.listener_mail_ratio,
                ending_ratio=self.structure.ending_ratio
            )
        user_prompt = self._build_user_prompt(theme, research_data, avoid_topics, excluded_topics)
        self.last_usage = None  # リセット
        
        try:
            # response_schemaを使用してスキーマ検証を有効化
            response_text, usage = self._call_api(system_prompt, user_prompt, use_schema=True)
            self.last_usage = usage
            script = self._parse_response(response_text)
            
            # 参考文献の件数をチェックし、超過している場合は警告と切り詰め
            if script.references and len(script.references) > 5:
                logger.warning(f"Geminiが{len(script.references)}件の参考文献を生成、5件に切り詰めます")
                script.references = script.references[:5]
            
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
                    response_text, usage = self._call_api(system_prompt, user_prompt, use_schema=True)
                    self.last_usage = usage
                    script = self._parse_response(response_text)
                    return script
                finally:
                    self.model_name = original_model
            raise
    
    def _call_api(self, system_prompt: str, user_prompt: str, use_schema: bool = False, phase: str = "scripting") -> tuple[str, GeminiUsage]:
        """Gemini APIを呼び出す
        
        Args:
            system_prompt: システムプロンプト
            user_prompt: ユーザープロンプト
            use_schema: Scriptスキーマを使用するかどうか
            phase: 実行フェーズ名（ログ記録用）
        
        Returns:
            tuple[str, GeminiUsage]: (レスポンステキスト, 使用量)
        """
        config_params = {
            "max_output_tokens": self.max_tokens,
            "temperature": 0.85,
            "response_mime_type": "application/json",  # JSONモード有効化
        }
        
        # 台本生成時はスキーマを指定して構造化出力を強制
        if use_schema:
            config_params["response_schema"] = Script
        
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{system_prompt}\n\n{user_prompt}")]
                )
            ],
            config=types.GenerateContentConfig(**config_params)
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
        
        # 実行ログ用: プロンプトとレスポンスを記録
        from datetime import datetime
        prompt_record = {
            "phase": phase,
            "api_provider": "gemini",
            "model_name": self.model_name,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": response.text,
            "timestamp": datetime.now().isoformat()
        }
        self.prompt_records.append(prompt_record)
        
        return response.text, usage
    
    def _build_part2_system_prompt(self) -> str:
        """第2部モード専用の強化システムプロンプトを構築"""
        return """あなたはプロのラジオ台本作家です。現在、番組の第2部を制作しています。

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

4. 【連続性の演出】
   - 可能であれば第1部の内容に軽く触れる（コールバックする）ことで、
     一つの番組としての自然な繋がりを演出してください
   - 「先ほどお話しした〇〇ですが、さらに深掘りすると…」のような自然な接続を心がけてください

5. 【価値の追加】
   - 第1部では触れられなかった側面、背景、応用例、将来展望などを提供してください
   - 視聴者が「第1部で知っていたことの全く新しい側面が見えた」と感じるような内容を目指してください

これらの制約を守りながら、第1部と合わせてあたかも一人の放送作家が一気に書き上げたような、
淀みのないスムーズな番組を制作してください。"""

    def _build_user_prompt(self, theme: str, research_data: Optional[ResearchResult], avoid_topics: Optional[str] = None, excluded_topics: Optional[str] = None) -> str:
        """ユーザープロンプトを構築"""
        prompt = f"## テーマ\n{theme}\n\n"
        
        if research_data:
            prompt += f"## リサーチ結果（{research_data.mode}モード）\n"
            prompt += f"{research_data.content}\n\n"
            
            # 参考リンク候補を追加
            if research_data.sources:
                prompt += "## <参考リンク候補>\n"
                prompt += "以下のリンク候補の中から、台本の内容に最も関連が深く、視聴者に有益なものを厳選してください。\n\n"
                
                for i, source in enumerate(research_data.sources, 1):
                    title = (source.title or "").strip() or f"ソース{i}"
                    url = (source.url or "").strip()
                    if url:
                        prompt += f"{i}. {title}: {url}\n"
                
                prompt += "\n"
        
        if excluded_topics and excluded_topics.strip():
            prompt += (
                "[PART 1 CONTEXT - 第2部モード]\n"
                "以下は第1部で放送済みの全内容です。第2部ではこれを前提知識として扱い、\n"
                "重複説明を避け、新しい視点からの深掘りや別の側面に焦点を当ててください。\n\n"
                f"{excluded_topics.strip()}\n\n"
                "【重要制約】\n"
                "- 第1部で説明済みの内容は、前提知識として簡潔に扱うか、全く異なる角度から深掘りしてください\n"
                "- 第1部で使われた特定のフレーズや定義と矛盾しない、一貫性のある言い回しを徹底してください\n"
                "- 可能であれば第1部の内容に軽く触れる（コールバックする）ことで、番組としての連続性を演出してください\n"
                "- 物理的な重複（同じ説明、同じ例え、同じデータ）は絶対に避けてください\n\n"
            )
        
        if avoid_topics and avoid_topics.strip():
            prompt += (
                "[NEGATIVE CONSTRAINTS]\n"
                "The user has explicitly requested to AVOID the following topics/keywords in this script:\n"
                f"\"{avoid_topics.strip()}\"\n\n"
                "STRICTLY FOLLOW this instruction. Do not mention, discuss, or allude to these topics.\n"
                "Focus on other aspects of the theme to ensure variety.\n\n"
            )
        
        prompt += "上記の情報を基に、ラジオ台本をJSON形式で作成してください。"
        return prompt
    
    def _parse_response(self, response_text: str) -> Script:
        """APIレスポンスからScriptオブジェクトを生成
        
        JSONモード + response_schemaにより、response_textは常に正しいJSON形式で返される
        Pydanticモデルで厳格なバリデーションを実施
        """
        try:
            # JSONをパース
            json_data = json.loads(response_text.strip())
            
            # Pydanticモデルでバリデーション（ここで検証エラーなら例外が出る）
            script_obj = Script(**json_data)
            
            console.print(f"[green]✓ Pydanticバリデーション成功[/green]")
            console.print(f"  総ターン数: {script_obj.total_turns}")
            
            return script_obj
            
        except json.JSONDecodeError as e:
            console.print(f"[red]✗ JSON解析エラー: {e}[/red]")
            console.print(f"[dim]レスポンス: {response_text[:200]}...[/dim]")
            raise
        except Exception as e:
            console.print(f"[red]✗ Pydanticバリデーションエラー: {e}[/red]")
            console.print(f"[dim]JSON: {response_text[:200]}...[/dim]")
            raise
    
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
    
