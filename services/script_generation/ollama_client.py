"""Ollama Client for Local LLM Script Generation

Uses OpenAI-compatible API to communicate with local Ollama server.
Simple implementation without complex reflection loops.
"""
import asyncio
import json
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from rich.console import Console

from core.interfaces import IScriptGenerator, ResearchResult
from core.models import AppConfig, Script, LLMUsage
from core.models.script import DialogueTurn, TurnType
from core.utils import sanitize_json_lightweight
from core.prompt_manager import PromptManager
from services.script_generation.time_expressions import get_time_expression

import logging

logger = logging.getLogger(__name__)
console = Console()


class OllamaClient(IScriptGenerator):
    """Ollama-based local LLM script generator
    
    Uses OpenAI-compatible API to communicate with local Ollama server.
    Simple implementation following the same flow as GeminiClient.
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        
        # Load Ollama configuration
        ollama_cfg = config.yaml.script_generator.ollama
        self.model_name = ollama_cfg.model
        self.base_url = ollama_cfg.base_url
        self.max_tokens = ollama_cfg.max_tokens
        self.temperature = ollama_cfg.temperature
        self.personalities = config.yaml.personalities
        self.structure = config.yaml.script_generator.structure
        self.prompt_manager = PromptManager()
        
        # Initialize OpenAI-compatible client for Ollama
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key="ollama"  # Dummy API key (Ollama doesn't require auth)
        )
        
        # Usage tracking
        self.last_usage: Optional[LLMUsage] = None
        self.prompt_records: list = []
    
    async def generate(
        self,
        theme: str,
        research_data: Optional[ResearchResult] = None,
        avoid_topics: Optional[str] = None,
        excluded_topics: Optional[str] = None
    ) -> Script:
        """Generate script using Ollama local LLM
        
        Args:
            theme: Script theme/topic
            research_data: Research results (optional)
            avoid_topics: Topics to avoid (Negative Prompt, optional)
            excluded_topics: Topics already covered in Part 1 (optional)
        
        Returns:
            Script: Generated script object
        """
        console.print(f"[cyan]Ollama で台本を生成中...[/cyan]")
        console.print(f"  テーマ: {theme}")
        console.print(f"  モデル: {self.model_name}")
        console.print(f"  リサーチデータ: {'あり' if research_data else 'なし'}")
        
        # Build prompts following GeminiClient pattern
        system_prompt = self._build_system_prompt(research_data, excluded_topics)
        user_prompt = self._build_user_prompt(theme, research_data, avoid_topics, excluded_topics)
        
        self.last_usage = None
        
        try:
            # Call Ollama API
            response_text, usage = await self._call_api(system_prompt, user_prompt)
            self.last_usage = usage
            script = self._parse_response(response_text)
            
            # Limit references to 5
            if script.references and len(script.references) > 5:
                logger.warning(f"Ollama generated {len(script.references)} references, trimming to 5")
                script.references = script.references[:5]
            
            console.print(f"[green]✓ 台本生成完了[/green] 対話数: {len(script.dialogue)}")
            if usage:
                console.print(f"  トークン: 入力 {usage.input_tokens:,} / 出力 {usage.output_tokens:,}")
            
            return script
            
        except Exception as e:
            console.print(f"[red]✗ Ollama API エラー: {e}[/red]")
            raise
    
    async def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        phase: str = "scripting"
    ) -> tuple[str, Optional[LLMUsage]]:
        """Call Ollama API via OpenAI-compatible endpoint
        
        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            phase: Execution phase (for logging)
        
        Returns:
            (response_text, usage_info)
        """
        from datetime import datetime
        
        # Prepare messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Retry logic
        max_retries = 2
        response = None
        
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    response_format={"type": "json_object"}  # Request JSON output
                )
                break  # Success
                
            except Exception as e:
                error_msg = str(e).lower()
                if ("timeout" in error_msg or "connection" in error_msg) and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    console.print(f"[yellow]接続エラー ({attempt + 1}/{max_retries})。{wait_time}秒後にリトライします...[/yellow]")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise
        
        # Extract response content
        response_text = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason
        
        # Log finish reason
        logger.debug(f"finish_reason: {finish_reason}")
        if finish_reason == "length":
            logger.warning("max_tokens limit reached. Output may be truncated.")
        
        # Extract usage
        usage = LLMUsage(
            provider="ollama",
            model_name=self.model_name,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            request_count=1
        )
        
        # Log prompt and response
        prompt_record = {
            "phase": phase,
            "api_provider": "ollama",
            "model_name": self.model_name,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": response_text,
            "timestamp": datetime.now().isoformat()
        }
        self.prompt_records.append(prompt_record)
        
        return response_text, usage
    
    def _build_system_prompt(
        self,
        research_data: Optional[ResearchResult] = None,
        excluded_topics: Optional[str] = None
    ) -> str:
        """Build system prompt based on research mode
        
        Args:
            research_data: Research results (for mode detection)
            excluded_topics: Part 1 context (for Part 2 mode)
        
        Returns:
            System prompt string
        """
        # Part 2 mode detection
        if excluded_topics and excluded_topics.strip():
            return self._build_part2_system_prompt()
        
        # Mode-specific prompts
        if research_data and research_data.mode == "weekly_digest":
            time_expr = get_time_expression("weekly_digest")
            return self.prompt_manager.get_script_prompt(
                "weekly_digest",
                title_prefix=time_expr["title_prefix"],
                intro_phrase=time_expr["intro_phrase"],
                outro_phrase=time_expr["outro_phrase"],
                theme=research_data.topic if research_data else "",
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
        research_data: Optional[ResearchResult],
        avoid_topics: Optional[str],
        excluded_topics: Optional[str]
    ) -> str:
        """Build user prompt with theme and research data
        
        Args:
            theme: Script theme
            research_data: Research results
            avoid_topics: Topics to avoid
            excluded_topics: Part 1 context for Part 2 mode
        
        Returns:
            User prompt string
        """
        prompt = f"## テーマ\n{theme}\n\n"
        
        if research_data and research_data.content:
            prompt += f"## リサーチ結果（{research_data.mode}モード）\n"
            prompt += f"{research_data.content}\n\n"
            
            # Add reference link candidates
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
                f'"{avoid_topics.strip()}"\n\n'
                "STRICTLY FOLLOW this instruction. Do not mention, discuss, or allude to these topics.\n"
                "Focus on other aspects of the theme to ensure variety.\n\n"
            )
        
        prompt += "上記の情報を基に、ラジオ台本をJSON形式で作成してください。"
        return prompt
    
    def _parse_response(self, response_text: str) -> Script:
        """Parse API response to Script object
        
        Args:
            response_text: JSON response text
        
        Returns:
            Script: Validated script object
        """
        try:
            # Parse JSON
            json_data = json.loads(response_text.strip(), strict=False)
            
            # Validate with Pydantic model
            script_obj = Script(**json_data)
            
            console.print(f"[green]✓ Pydanticバリデーション成功[/green]")
            console.print(f"  総ターン数: {script_obj.total_turns}")
            
            return script_obj
            
        except json.JSONDecodeError as e:
            console.print(f"[yellow]⚠ JSON解析エラー、サニタイズ再試行: {e}[/yellow]")
            sanitized_text = sanitize_json_lightweight(response_text)
            
            try:
                json_data = json.loads(sanitized_text, strict=False)
                script_obj = Script(**json_data)
                
                console.print(f"[green]✓ サニタイズ後のPydanticバリデーション成功[/green]")
                console.print(f"  総ターン数: {script_obj.total_turns}")
                return script_obj
                
            except Exception as retry_error:
                console.print(f"[red]✗ サニタイズ後も解析失敗: {retry_error}[/red]")
                console.print(f"[dim]元レスポンス: {response_text[:200]}...[/dim]")
                raise
                
        except Exception as e:
            console.print(f"[red]✗ Pydanticバリデーションエラー: {e}[/red]")
            console.print(f"[dim]JSON: {response_text[:200]}...[/dim]")
            raise
    
    async def create_research_plan(self, theme: str, mode: str, instruction: Optional[str] = None):
        """Create research plan (delegates to Gemini for now)
        
        Note: Research planning is currently handled by GeminiClient.
        This method is here for interface compatibility.
        """
        raise NotImplementedError(
            "Research planning is currently handled by GeminiClient. "
            "Use GeminiClient.create_research_plan() instead."
        )

    def generate_packaging_prompt(self, theme: str, script_summary: str) -> str:
        """packaging プロンプトを使用して YouTube メタデータ JSON を生成

        他プロバイダー（Gemini/OpenAI/Anthropic）と同様のシグネチャで同期呼び出しされる
        (workflow._generate_youtube_metadata から同期的にコールされるため)。
        Ollama は通常 AsyncOpenAI を使うが、このメソッドは同期コンテキストで動作させるため
        openai.OpenAI (sync client) を都度生成して Ollama の OpenAI 互換エンドポイントを叩く。

        Args:
            theme: テーマ（字幕・タイトル生成用）
            script_summary: 台本の要約

        Returns:
            生成された YouTube メタデータ JSON 文字列
        """
        from openai import OpenAI  # sync client (avoids asyncio.run inside possibly-running loop)

        packaging_prompt = self.prompt_manager.get_prompt("packaging", "default")
        formatted_prompt = packaging_prompt.format(
            theme=theme,
            script_summary=script_summary,
        )

        # Use a synchronous OpenAI-compatible client against the Ollama endpoint.
        # Creating a client per call is cheap and avoids mixing async/sync lifetimes.
        sync_client = OpenAI(
            base_url=self.base_url,
            api_key="ollama",  # Dummy; Ollama does not require auth
        )

        response = sync_client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": formatted_prompt}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""
