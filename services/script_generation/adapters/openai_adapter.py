"""OpenAI Provider Adapter - Infrastructure layer implementation

Step 4 v2 (2026-05-10) @deprecated: 旧 Gemini 自動経路の provider-agnostic 構成要素として
残置。HITL 経路でのみ呼ばれる。Step 5 で再評価予定。
"""
import asyncio
import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI, RateLimitError, APIConnectionError, APITimeoutError

from core.interfaces.llm_port import (
    ILLMPort, LLMRequest, LLMResponse, LLMUsage,
    LLMConnectionError, LLMRateLimitError, LLMResponseError
)


class OpenAIAdapter(ILLMPort):
    """OpenAI SDK adapter with async wrapper
    
    Wraps synchronous OpenAI SDK in async interface for consistency.
    """
    
    def __init__(self, api_key: str, default_model: str):
        self._client = OpenAI(api_key=api_key)
        self._default_model = default_model
        # Bounded thread pool to prevent unlimited thread spawning
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="openai-")
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate content with OpenAI (async wrapper)"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,  # Use bounded thread pool
            self._generate_sync,
            request
        )
    
    def _generate_sync(self, request: LLMRequest) -> LLMResponse:
        """Synchronous OpenAI API call (runs in thread pool)"""
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt}
        ]
        
        # OpenAI-specific: JSON mode
        extra_params = {}
        if request.response_format == "json":
            extra_params["response_format"] = {"type": "json_object"}
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=request.model or self._default_model,
                    messages=messages,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    **extra_params
                )
                
                # Extract response
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                usage = LLMUsage(
                    provider="openai",
                    model_name=request.model or self._default_model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    request_count=1
                )
                
                return LLMResponse(
                    content=content,
                    usage=usage,
                    finish_reason=finish_reason,
                    raw_response=response
                )
                
            except RateLimitError as e:
                # OpenAI SDK's native rate limit exception
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMRateLimitError(f"OpenAI rate limit: {e}") from e
            
            except (APIConnectionError, APITimeoutError) as e:
                # OpenAI SDK's native connection/timeout exceptions
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMConnectionError(f"OpenAI connection error: {e}") from e
            
            except Exception as e:
                # Unknown error - don't retry
                last_error = e
                raise LLMResponseError(f"OpenAI API error: {e}") from e
        
        raise LLMConnectionError(f"Max retries exceeded: {last_error}")
    
    async def health_check(self) -> bool:
        """Check OpenAI API availability"""
        try:
            test_request = LLMRequest(
                system_prompt="Test",
                user_prompt="Reply with 'OK'",
                model=self._default_model,
                max_tokens=10,
                temperature=0.0
            )
            await self.generate(test_request)
            return True
        except Exception:
            return False
    
    @property
    def provider_name(self) -> str:
        return "openai"
    
    @property
    def model_name(self) -> str:
        return self._default_model
