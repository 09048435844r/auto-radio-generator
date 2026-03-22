"""Gemini APIを使用した台本生成クライアント"""
import json
import re
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.interfaces import IScriptGenerator, ResearchResult
from core.models import Script, AppConfig, LLMUsage, ResearchPlan

# Backward compatibility alias
GeminiUsage = LLMUsage
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
        
        # Safety settings: 最も緩い設定（医療系ワード等での誤爆防止）
        self.default_safety_settings = [
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_NONE"
            ),
        ]
        
        # 最後のAPI呼び出しの使用量を保持
        self.last_usage: LLMUsage | None = None
        
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
    
    async def generate(self, theme: str, research_data: Optional[ResearchResult] = None, avoid_topics: Optional[str] = None, excluded_topics: Optional[str] = None) -> Script:
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
                    self.last_usage = LLMUsage(
                        provider="gemini",
                        model_name="mock",
                        input_tokens=0,
                        output_tokens=0,
                        request_count=0
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
    
    def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        use_schema: bool = False,
        phase: str = "scripting",
        model_override: Optional[str] = None
    ) -> tuple[str, Optional[GeminiUsage]]:
        """Gemini APIを呼び出し
        
        Args:
            system_prompt: システムプロンプト
            user_prompt: ユーザープロンプト
            use_schema: スキーマを使用するか
            phase: 実行フェーズ（ログ用）
            model_override: モデル名のオーバーライド（軽量モデル用）
            
        Returns:
            (レスポンステキスト, 使用量情報)
        """
        import time
        import re
        
        # 第2部モード（excluded_topicsがある場合）はtemperatureを下げる
        is_part2 = bool(re.search(r'第1部.*放送済み', user_prompt))
        
        # モデルの選択（オーバーライド優先）
        model_to_use = model_override if model_override else self.model_name
        
        config_params = {
            "max_output_tokens": 16384,  # 長文台本での途切れ防止のため固定値に設定
            "temperature": 0.7 if is_part2 else 0.85,
            "response_mime_type": "application/json",  # JSONモード有効化
            "safety_settings": self.default_safety_settings,  # 医療系ワード等での誤爆防止
        }
        
        # デバッグ: max_output_tokensの設定値を確認
        console.print(f"[dim]API呼び出し設定: max_output_tokens={config_params['max_output_tokens']}, model={model_to_use}[/dim]")
        
        # 台本生成時はスキーマを指定して構造化出力を強制
        if use_schema:
            config_params["response_schema"] = Script
        
        # リトライ処理
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=model_to_use,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part(text=f"{system_prompt}\n\n{user_prompt}")]
                        )
                    ],
                    config=types.GenerateContentConfig(**config_params)
                )
                break  # 成功したらループを抜ける
            except Exception as e:
                error_msg = str(e).lower()
                if ("disconnected" in error_msg or "timeout" in error_msg or "connection" in error_msg) and attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 指数バックオフ: 1秒, 2秒
                    console.print(f"[yellow]接続エラー ({attempt + 1}/{max_retries})。{wait_time}秒後にリトライします...[/yellow]")
                    time.sleep(wait_time)
                    continue
                else:
                    raise  # リトライ上限または回復不可能なエラー
        
        # finish_reasonをログ出力（途切れ原因の特定用）
        if response.candidates and len(response.candidates) > 0:
            import logging
            logger = logging.getLogger(__name__)
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
            logger.debug(f"finish_reason: {finish_reason}")
            
            # 途切れの可能性がある場合は警告
            if finish_reason in ['MAX_TOKENS', 'SAFETY', 'RECITATION']:
                logger.warning(f"出力が途中で終了した可能性: {finish_reason}")
                if finish_reason == 'MAX_TOKENS':
                    logger.warning("max_output_tokens上限到達。出力が切り詰められました。")
                elif finish_reason == 'SAFETY':
                    logger.warning("セーフティフィルターが発動。特定のワードが原因の可能性があります。")
                elif finish_reason == 'RECITATION':
                    logger.warning("著作権保護により出力が遮断されました。")
        
        # 使用量を取得
        usage = LLMUsage(
            provider="gemini",
            model_name=model_to_use,
            input_tokens=0,
            output_tokens=0,
            request_count=1
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
            "model_name": model_to_use,
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
            json_data = json.loads(response_text.strip(), strict=False)
            
            # Pydanticモデルでバリデーション（ここで検証エラーなら例外が出る）
            script_obj = Script(**json_data)
            
            console.print(f"[green]✓ Pydanticバリデーション成功[/green]")
            console.print(f"  総ターン数: {script_obj.total_turns}")
            
            return script_obj
            
        except json.JSONDecodeError as e:
            console.print(f"[yellow]⚠ JSON解析エラー、サニタイズ再試行: {e}[/yellow]")
            sanitized_text = self._sanitize_json_response(response_text)

            try:
                json_data = json.loads(sanitized_text, strict=False)
                script_obj = Script(**json_data)

                console.print(f"[green]✓ サニタイズ後のPydanticバリデーション成功[/green]")
                console.print(f"  総ターン数: {script_obj.total_turns}")
                return script_obj
            except Exception as retry_error:
                console.print(f"[red]✗ サニタイズ後も解析失敗: {retry_error}[/red]")
                console.print(f"[dim]元レスポンス: {response_text[:200]}...[/dim]")
                console.print(f"[dim]サニタイズ後: {sanitized_text[:200]}...[/dim]")
                raise
        except Exception as e:
            console.print(f"[red]✗ Pydanticバリデーションエラー: {e}[/red]")
            console.print(f"[dim]JSON: {response_text[:200]}...[/dim]")
            raise

    def _sanitize_json_response(self, text: str) -> str:
        """軽微なJSONサニタイズ（Markdown code fence除去のみ）"""
        sanitized = re.sub(r'^\s*```json\s*', '', text, flags=re.IGNORECASE)
        sanitized = re.sub(r'\s*```\s*$', '', sanitized)
        return sanitized.strip()
    
    def _build_research_plan_prompt(self, mode: str) -> str:
        """検索計画作成用のシステムプロンプトを構築
        
        Args:
            mode: リサーチモード (trivia/debate/weekly_digest/voices)
        """
        base_prompt = """あなたはラジオ番組の構成作家です。
テーマを**極限まで深掘り**するための「高密度な検索クエリ」を考案してください。

## タスク
テーマに対して、以下の3つの観点から**具体的で構造化された**検索クエリを作成してください。
各クエリは、Perplexityが「事実・数字・専門家の見解・最新動向」を含む2500文字以上の詳細なレポートを返せるよう、**求める情報の種類を明示すること**。
抽象的な表現（「意外な」「面白い」など）は避け、具体的な情報要求に置き換えること。
"""
        
        # モード別の指示
        mode_instructions = {
            "trivia": """1. **歴史的発展と起源（構造化クエリ）**
   - 形式: "○○の歴史的発展: 起源から現在までの主要マイルストーン、年代別の技術的ブレークスルー、統計データ、重要人物・組織の役割、社会的影響を含む詳細な年表"
   - 目的: 具体的な年月日・人名・数字を含む歴史レポート

2. **知られていない事実・開発秘話（深掘りクエリ）**
   - 形式: "○○に関する意外な事実と開発秘話: 一般に知られていない技術的詳細、失敗事例と教訓、専門家のみが知る裏事情、統計データ、社会的影響の詳細分析"
   - 目的: 表層的でない、専門家レベルの深い情報

3. **多角的分析（技術・社会・経済）**
   - 形式: "○○の技術的・社会的・経済的分析: 仕組みの詳細、市場規模と成長率、競合比較、専門家の見解と引用、今後10年の展望、未解決の課題"
   - 目的: 複数の観点からの包括的な現状把握""",

            "debate": """1. **賛成派の主張と根拠（構造化クエリ）**
   - 形式: "○○を支持する根拠: 賛成派の主要主張3つ以上、各主張を裏付ける統計データと研究結果（出典付き）、著名な支持者・組織名と具体的な発言、実際の成功事例と数値効果"
   - 目的: データと引用に裏付けられた賛成論

2. **反対派の主張と根拠（構造化クエリ）**
   - 形式: "○○への批判と反証: 反対派の主要主張3つ以上、各主張を裏付けるデータと研究結果（出典付き）、著名な批判者・組織名と具体的な発言、実際の失敗事例と問題点"
   - 目的: データと引用に裏付けられた反対論

3. **議論の焦点と専門家コンセンサス**
   - 形式: "○○をめぐる議論の構造: 両者が一致しない核心的論点、学術界・業界の現在の主流見解、直近1年の重要な研究発表・政策変更、今後の議論の行方の予測"
   - 目的: 議論の全体像と最新の専門家見解""",

            "weekly_digest": """1. **最新ニュースと事実（5W1Hクエリ）**
   - 形式: "○○ 最新ニュース: 直近1ヶ月以内の重要出来事を5W1H（いつ・どこで・誰が・何を・なぜ・どのように）で詳細報告、定量的データ（金額・人数・割合）、業界への影響"
   - 注意: 「今週」「this week」などの厳密な期間指定は避ける

2. **世論・SNS反応の定量分析**
   - 形式: "○○ SNS反応分析 最近: 主要ハッシュタグと投稿規模、賛否感情の分布、世代別・属性別の反応の違い、バイラル投稿の内容、インフルエンサーの発言内容"
   - 目的: 数値で裏付けられた世論の実態

3. **今後の展望と専門家予測**
   - 形式: "○○ 今後の展望 専門家予測: 直近発表された研究・政策・業界動向、複数専門家の具体的な予測と根拠、リスクシナリオと機会シナリオ、タイムライン"
   - 目的: 根拠ある将来予測""",

            "voices": """1. **SNS・口コミの定量・定性分析**
   - 形式: "○○ ユーザー体験談と口コミ分析: 実際の利用者の具体的な体験、賛否の割合と感情分布、年齢層・属性別の評価の違い、繰り返し言及されるメリット・デメリット、数値化できる満足度データ"
   - 目的: 統計的裏付けのある利用者の声

2. **体験談・成功/失敗事例の詳細**
   - 形式: "○○ 実体験レポート: 具体的な使用前後の変化（数値で）、成功した人の条件と要因、失敗した人のパターンと原因、長期利用者と短期利用者の評価の差、専門家による評価"
   - 目的: 具体的で再現性のある事例情報

3. **批判・懸念・支持の根拠**
   - 形式: "○○ 賛否の声: 主要な批判点と懸念（根拠付き）、支持者の具体的なメリット体験、専門家からの肯定・否定的評価の引用、メディア報道の傾向と論調"
   - 目的: 多角的な評価の全体像""",

            "lecture": """1. **基礎概念と仕組みの段階的解説**
   - 形式: "○○ とは何か: 専門用語を使わない定義、身近なものへの比喩3つ以上、技術的な仕組みを段階的に説明、重要なコンポーネントと役割、市場規模・ユーザー数などの数値"
   - 目的: 初心者が理解できる構造化された解説

2. **実際の活用事例と効果（具体例集）**
   - 形式: "○○ 活用事例: 具体的な企業名・製品名・プロジェクト名、導入前後の変化（数値で示す）、成功事例5つ以上、失敗事例と教訓、業界別の活用方法の違い"
   - 目的: 実践的な活用イメージの構築

3. **誤解・落とし穴・将来性の深掘り**
   - 形式: "○○ よくある誤解と実態: 誤解の内容と正しい理解（3つ以上）、誤解が生じる原因、実際の被害・損失事例、専門家が指摘する注意点、今後5-10年の技術的発展予測と根拠"
   - 目的: リスクと可能性の両面把握"""
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
- クエリは**極めて具体的**で、Perplexityが2500文字以上の詳細レポートを返せる内容にする
- 各クエリには「求める情報の種類」を明示する（例: 統計データ、専門家の見解、最新動向など）
- 抽象的な表現（「意外な」「面白い」など）は避け、具体的な情報要求に置き換える
- 各クエリは異なる観点から情報を集められるようにする
- angleは視聴者が興味を持つような切り口を提案する

## クエリの良い例・悪い例
❌ 悪い例: "○○の意外な歴史"
✅ 良い例: "○○の歴史的発展: 起源から現在までの主要マイルストーン、技術的ブレークスルー、統計データ、重要人物の役割を含む詳細な年表"

❌ 悪い例: "○○の面白いエピソード"
✅ 良い例: "○○に関する意外な事実と開発秘話: 一般に知られていない技術的詳細、失敗事例と教訓、専門家の見解（引用）、社会的影響の詳細分析"
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
    
