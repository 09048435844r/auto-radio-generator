"""OpenAI Script Generator Client

Uses OpenAI's Structured Outputs feature to generate radio scripts with guaranteed JSON schema compliance.
"""
import time
from typing import Optional, TYPE_CHECKING
from openai import OpenAI
from rich.console import Console

from core.interfaces.script_generator import IScriptGenerator
from core.models import Script, AppConfig, LLMUsage

from core.prompt_manager import PromptManager

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult

console = Console()


class OpenAIClient(IScriptGenerator):
    """OpenAI-based script generator using Structured Outputs"""
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        
        api_key = config.env.openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        self.client = OpenAI(api_key=api_key)
        
        # Load configuration
        self.model_name = config.yaml.script_generator.openai.model
        self.fallback_model = config.yaml.script_generator.openai.fallback_model
        self.max_tokens = config.yaml.script_generator.openai.max_tokens
        self.temperature = config.yaml.script_generator.openai.temperature
        self.structure = config.yaml.script_generator.structure
        self.personalities = config.yaml.personalities
        self.prompt_manager = PromptManager()
        
        # Usage tracking
        self.last_usage: Optional[LLMUsage] = None
        self.prompt_records: list = []
    
    async def generate(
        self,
        theme: str,
        research_data: Optional["ResearchResult"] = None,
        avoid_topics: Optional[str] = None,
        excluded_topics: Optional[str] = None
    ) -> Script:
        """Generate script using OpenAI with Structured Outputs
        
        Args:
            theme: Video theme/topic
            research_data: Research results (optional)
            avoid_topics: Topics to avoid (optional)
            excluded_topics: Topics already covered in Part 1 (optional)
        
        Returns:
            Script: Generated script with guaranteed schema compliance
        """
        console.print(f"[cyan]Generating script with OpenAI ({self.model_name})...[/cyan]")
        
        # Build prompts
        system_prompt = self._build_system_prompt(research_data, theme)
        user_prompt = self._build_user_prompt(theme, research_data, avoid_topics, excluded_topics)
        
        self.last_usage = None
        
        try:
            # Use Structured Outputs for guaranteed JSON compliance
            response_text, usage = self._call_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                use_structured_outputs=True
            )
            
            self.last_usage = usage
            script = self._parse_response(response_text)
            
            # Limit references to 5
            if script.references and len(script.references) > 5:
                console.print(f"[yellow]Trimming {len(script.references)} references to 5[/yellow]")
                script.references = script.references[:5]
            
            console.print(f"[green]✓ Script generation complete[/green] Dialogue turns: {len(script.dialogue)}")
            if usage:
                console.print(f"  Tokens: input {usage.input_tokens:,} / output {usage.output_tokens:,}")
            
            return script
            
        except Exception as e:
            console.print(f"[red]✗ OpenAI API error: {e}[/red]")
            
            # Fallback to alternative model
            if self.model_name != self.fallback_model:
                console.print(f"[yellow]Retrying with fallback model {self.fallback_model}...[/yellow]")
                original_model = self.model_name
                self.model_name = self.fallback_model
                try:
                    response_text, usage = self._call_api(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        use_structured_outputs=True
                    )
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
        use_structured_outputs: bool = False,
        phase: str = "scripting",
        model_override: Optional[str] = None
    ) -> tuple[str, Optional[LLMUsage]]:
        """Call OpenAI API with Structured Outputs
        
        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            use_structured_outputs: Use Structured Outputs feature
            phase: Execution phase (for logging)
            model_override: Model name override
        
        Returns:
            (response_text, usage_info)
        """
        import json
        from datetime import datetime
        
        model_to_use = model_override if model_override else self.model_name
        
        # Determine token parameter name based on model
        # gpt-5 series, o1 series, o3 series use max_completion_tokens
        use_max_completion_tokens = (
            model_to_use.startswith("gpt-5") or 
            model_to_use.startswith("o1-") or 
            model_to_use.startswith("o3-")
        )
        
        token_param_name = "max_completion_tokens" if use_max_completion_tokens else "max_tokens"
        console.print(f"[dim]API call settings: {token_param_name}={self.max_tokens}, model={model_to_use}[/dim]")
        
        # Retry logic
        max_retries = 2
        for attempt in range(max_retries):
            try:
                if use_structured_outputs:
                    # Use Structured Outputs (beta feature)
                    # Build kwargs dynamically based on model
                    api_kwargs = {
                        "model": model_to_use,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "response_format": Script,
                        "temperature": self.temperature
                    }
                    
                    # Add appropriate token parameter
                    if use_max_completion_tokens:
                        api_kwargs["max_completion_tokens"] = self.max_tokens
                    else:
                        api_kwargs["max_tokens"] = self.max_tokens
                    
                    completion = self.client.beta.chat.completions.parse(**api_kwargs)
                    
                    # Extract parsed object
                    parsed_script = completion.choices[0].message.parsed
                    if parsed_script is None:
                        raise ValueError("Structured Outputs returned None")
                    
                    # Convert to JSON string for consistency
                    response_text = parsed_script.model_dump_json()
                    
                else:
                    # Standard completion
                    api_kwargs = {
                        "model": model_to_use,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": self.temperature,
                        "response_format": {"type": "json_object"}
                    }
                    
                    # Add appropriate token parameter
                    if use_max_completion_tokens:
                        api_kwargs["max_completion_tokens"] = self.max_tokens
                    else:
                        api_kwargs["max_tokens"] = self.max_tokens
                    
                    completion = self.client.chat.completions.create(**api_kwargs)
                    response_text = completion.choices[0].message.content
                
                break  # Success
                
            except Exception as e:
                error_msg = str(e).lower()
                if ("timeout" in error_msg or "connection" in error_msg) and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    console.print(f"[yellow]Connection error ({attempt + 1}/{max_retries}). Retrying in {wait_time}s...[/yellow]")
                    time.sleep(wait_time)
                    continue
                else:
                    raise
        
        # Log finish_reason
        import logging
        logger = logging.getLogger(__name__)
        finish_reason = completion.choices[0].finish_reason
        logger.debug(f"finish_reason: {finish_reason}")
        
        if finish_reason in ['length', 'content_filter']:
            logger.warning(f"Output may be truncated: {finish_reason}")
            if finish_reason == 'length':
                logger.warning("max_tokens limit reached")
            elif finish_reason == 'content_filter':
                logger.warning("Content filter triggered")
        
        # Extract usage
        usage = LLMUsage(
            provider="openai",
            model_name=model_to_use,
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
            request_count=1
        )
        
        # Log prompt and response
        prompt_record = {
            "phase": phase,
            "api_provider": "openai",
            "model_name": model_to_use,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": response_text,
            "timestamp": datetime.now().isoformat()
        }
        self.prompt_records.append(prompt_record)
        
        return response_text, usage
    
    def _parse_response(self, response_text: str) -> Script:
        """Parse API response to Script object
        
        Args:
            response_text: JSON response text
        
        Returns:
            Script: Validated script object
        """
        import json
        
        try:
            json_data = json.loads(response_text.strip())
            script_obj = Script(**json_data)
            
            console.print(f"[green]✓ Pydantic validation successful[/green]")
            console.print(f"  Total turns: {script_obj.total_turns}")
            
            return script_obj
            
        except json.JSONDecodeError as e:
            console.print(f"[red]✗ JSON parse error: {e}[/red]")
            console.print(f"[dim]Response: {response_text[:200]}...[/dim]")
            raise
        except Exception as e:
            console.print(f"[red]✗ Pydantic validation error: {e}[/red]")
            console.print(f"[dim]JSON: {response_text[:200]}...[/dim]")
            raise
    
    def _build_system_prompt(self, research_data: Optional["ResearchResult"] = None, theme: str = "") -> str:
        """Build system prompt based on research mode"""
        if research_data and research_data.mode == "weekly_digest":
            from services.script_generation.time_expressions import get_time_expression
            time_expr = get_time_expression("weekly_digest")
            return self.prompt_manager.get_script_prompt(
                "weekly_digest",
                title_prefix=time_expr["title_prefix"],
                intro_phrase=time_expr["intro_phrase"],
                outro_phrase=time_expr["outro_phrase"],
                theme=theme,
                main_char=self.personalities.main,
                sub_char=self.personalities.sub,
                main=self.personalities.main,
                sub=self.personalities.sub
            )
        elif research_data and research_data.mode == "lecture":
            return self.prompt_manager.get_script_prompt(
                "lecture",
                theme="",
                main_char=self.personalities.main,
                sub_char=self.personalities.sub,
                main=self.personalities.main,
                sub=self.personalities.sub
            )
        else:
            return self.prompt_manager.get_script_prompt(
                "standard",
                main_char=self.personalities.main,
                sub_char=self.personalities.sub,
                main=self.personalities.main,
                sub=self.personalities.sub,
                main_topic_ratio=self.structure.main_topic_ratio,
                listener_mail_ratio=self.structure.listener_mail_ratio,
                ending_ratio=self.structure.ending_ratio
            )
    
    def _build_user_prompt(
        self,
        theme: str,
        research_data: Optional["ResearchResult"],
        avoid_topics: Optional[str],
        excluded_topics: Optional[str]
    ) -> str:
        """Build user prompt with theme and research data"""
        prompt = f"テーマ: {theme}\n\n"
        
        if research_data and research_data.content:
            prompt += f"[RESEARCH DATA]\n{research_data.content}\n\n"
        
        if excluded_topics and excluded_topics.strip():
            prompt += (
                "[PART 1 CONTENT (Already Covered)]\n"
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
        
        # OpenAIで生成（_call_apiメソッドを使用、Structured Outputsは不要）
        response_text, _ = self._call_api(
            system_prompt="",
            user_prompt=formatted_prompt,
            use_structured_outputs=False  # JSON出力のみなのでStructured Outputsは使わない
        )
        return response_text
    
    async def create_research_plan(self, theme: str, mode: str, instruction: Optional[str] = None):
        """Create research plan (delegates to Gemini for now)
        
        Note: Research planning is currently handled by GeminiClient.
        This method is here for interface compatibility.
        """
        raise NotImplementedError(
            "Research planning is currently handled by GeminiClient. "
            "Use GeminiClient.create_research_plan() instead."
        )
