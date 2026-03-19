"""Anthropic Script Generator Client

Uses Anthropic's Claude with Tool Calling for structured JSON output.
"""
import time
import json
from typing import Optional, TYPE_CHECKING
from anthropic import Anthropic
from rich.console import Console

from core.interfaces.script_generator import IScriptGenerator
from core.models import Script, AppConfig, LLMUsage

# Backward compatibility alias
GeminiUsage = LLMUsage
from core.prompt_manager import PromptManager

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult

console = Console()


class AnthropicClient(IScriptGenerator):
    """Anthropic Claude-based script generator using Tool Calling"""
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        
        api_key = config.env.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        
        self.client = Anthropic(api_key=api_key)
        
        # Load configuration
        self.model_name = config.yaml.script_generator.anthropic.model
        self.max_tokens = config.yaml.script_generator.anthropic.max_tokens
        self.temperature = config.yaml.script_generator.anthropic.temperature
        self.structure = config.yaml.script_generator.structure
        self.personalities = config.yaml.personalities
        self.prompt_manager = PromptManager()
        
        # Usage tracking
        self.last_usage: Optional[GeminiUsage] = None
        self.prompt_records: list = []
    
    async def generate(
        self,
        theme: str,
        research_data: Optional["ResearchResult"] = None,
        avoid_topics: Optional[str] = None,
        excluded_topics: Optional[str] = None
    ) -> Script:
        """Generate script using Anthropic Claude
        
        Args:
            theme: Video theme/topic
            research_data: Research results (optional)
            avoid_topics: Topics to avoid (optional)
            excluded_topics: Topics already covered in Part 1 (optional)
        
        Returns:
            Script: Generated script
        """
        console.print(f"[cyan]Generating script with Anthropic ({self.model_name})...[/cyan]")
        
        # Build prompts
        system_prompt = self._build_system_prompt(research_data, theme)
        user_prompt = self._build_user_prompt(theme, research_data, avoid_topics, excluded_topics)
        
        self.last_usage = None
        
        try:
            response_text, usage = self._call_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                use_tools=True
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
            console.print(f"[red]✗ Anthropic API error: {e}[/red]")
            raise
    
    def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        use_tools: bool = False,
        phase: str = "scripting"
    ) -> tuple[str, Optional[GeminiUsage]]:
        """Call Anthropic API with Tool Calling
        
        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            use_tools: Use Tool Calling for structured output
            phase: Execution phase (for logging)
        
        Returns:
            (response_text, usage_info)
        """
        from datetime import datetime
        
        console.print(f"[dim]API call settings: max_tokens={self.max_tokens}, model={self.model_name}[/dim]")
        
        # Define tool schema for structured output
        tools = [
            {
                "name": "generate_radio_script",
                "description": "Generate a radio script in JSON format with title, description, and dialogue",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "YouTube video title"
                        },
                        "thumbnail_title": {
                            "type": "string",
                            "description": "Short title for thumbnail (15 chars max)"
                        },
                        "description": {
                            "type": "string",
                            "description": "YouTube description with hashtags"
                        },
                        "dialogue": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "speaker": {
                                        "type": "string",
                                        "enum": ["A", "B"],
                                        "description": "Speaker ID"
                                    },
                                    "text": {
                                        "type": "string",
                                        "description": "Dialogue text"
                                    },
                                    "section": {
                                        "type": "string",
                                        "description": "Section marker (optional)"
                                    },
                                    "chapter_title": {
                                        "type": "string",
                                        "description": "Chapter title (optional)"
                                    }
                                },
                                "required": ["speaker", "text"]
                            }
                        },
                        "references": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            },
                            "description": "Reference URLs (max 5)"
                        }
                    },
                    "required": ["title", "thumbnail_title", "description", "dialogue"]
                }
            }
        ] if use_tools else None
        
        # Retry logic
        max_retries = 2
        for attempt in range(max_retries):
            try:
                if use_tools:
                    # Use Tool Calling
                    message = self.client.messages.create(
                        model=self.model_name,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        system=system_prompt,
                        messages=[
                            {"role": "user", "content": user_prompt}
                        ],
                        tools=tools,
                        tool_choice={"type": "tool", "name": "generate_radio_script"}
                    )
                    
                    # Extract tool use result
                    tool_use = None
                    for block in message.content:
                        if block.type == "tool_use" and block.name == "generate_radio_script":
                            tool_use = block
                            break
                    
                    if tool_use is None:
                        raise ValueError("No tool_use block found in response")
                    
                    # Convert tool input to JSON string
                    response_text = json.dumps(tool_use.input, ensure_ascii=False)
                    
                else:
                    # Standard completion with JSON instruction
                    message = self.client.messages.create(
                        model=self.model_name,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        system=system_prompt + "\n\nYou MUST respond with valid JSON only. No other text.",
                        messages=[
                            {"role": "user", "content": user_prompt}
                        ]
                    )
                    
                    # Extract text content
                    text_content = None
                    for block in message.content:
                        if block.type == "text":
                            text_content = block.text
                            break
                    
                    if text_content is None:
                        raise ValueError("No text content found in response")
                    
                    response_text = text_content
                
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
        
        # Log stop_reason
        stop_reason = message.stop_reason
        console.print(f"[dim]stop_reason: {stop_reason}[/dim]")
        
        if stop_reason in ['max_tokens']:
            console.print(f"[yellow]⚠ Output may be truncated: {stop_reason}[/yellow]")
            console.print(f"[yellow]  → max_tokens limit reached[/yellow]")
        
        # Extract usage
        usage = LLMUsage(
            provider="anthropic",
            model_name=self.model_name,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            request_count=1
        )
        
        # Log prompt and response
        prompt_record = {
            "phase": phase,
            "api_provider": "anthropic",
            "model_name": self.model_name,
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
        
        prompt += "上記の情報を基に、ラジオ台本を生成してください。generate_radio_script ツールを使用してください。"
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
        
        # Anthropicで生成（_call_apiメソッドを使用、Tool Callingは不要）
        response_text, _ = self._call_api(
            system_prompt="",
            user_prompt=formatted_prompt,
            use_tools=False  # JSON出力のみなのでTool Callingは使わない
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
