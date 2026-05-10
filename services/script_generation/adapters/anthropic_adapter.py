"""Anthropic Provider Adapter - Infrastructure layer implementation

Step 4 v2 (2026-05-10) @deprecated: 旧 Gemini 自動経路の provider-agnostic 構成要素として
残置。HITL 経路でのみ呼ばれる。Step 5 で再評価予定。
"""
import asyncio
import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from anthropic import Anthropic, RateLimitError, APIConnectionError, APITimeoutError

from core.interfaces.llm_port import (
    ILLMPort, LLMRequest, LLMResponse, LLMUsage,
    LLMConnectionError, LLMRateLimitError, LLMResponseError
)


class AnthropicAdapter(ILLMPort):
    """Anthropic SDK adapter with async wrapper
    
    Wraps synchronous Anthropic SDK in async interface for consistency.
    """
    
    def __init__(self, api_key: str, default_model: str):
        self._client = Anthropic(api_key=api_key)
        self._default_model = default_model
        # Bounded thread pool to prevent unlimited thread spawning
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="anthropic-")
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate content with Anthropic (async wrapper)"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,  # Use bounded thread pool
            self._generate_sync,
            request
        )
    
    def _generate_sync(self, request: LLMRequest) -> LLMResponse:
        """Synchronous Anthropic API call (runs in thread pool)"""
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = self._client.messages.create(
                    model=request.model or self._default_model,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    system=request.system_prompt,
                    messages=[
                        {"role": "user", "content": request.user_prompt}
                    ]
                )
                
                # Extract response
                content = response.content[0].text
                finish_reason = response.stop_reason or "stop"
                usage = LLMUsage(
                    provider="anthropic",
                    model_name=request.model or self._default_model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    request_count=1
                )
                
                return LLMResponse(
                    content=content,
                    usage=usage,
                    finish_reason=finish_reason,
                    raw_response=response
                )
                
            except RateLimitError as e:
                # Anthropic SDK's native rate limit exception
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMRateLimitError(f"Anthropic rate limit: {e}") from e
            
            except (APIConnectionError, APITimeoutError) as e:
                # Anthropic SDK's native connection/timeout exceptions
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMConnectionError(f"Anthropic connection error: {e}") from e
            
            except Exception as e:
                # Unknown error - don't retry
                last_error = e
                raise LLMResponseError(f"Anthropic API error: {e}") from e
        
        raise LLMConnectionError(f"Max retries exceeded: {last_error}")
    
    async def health_check(self) -> bool:
        """Check Anthropic API availability"""
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
        return "anthropic"
    
    @property
    def model_name(self) -> str:
        return self._default_model
