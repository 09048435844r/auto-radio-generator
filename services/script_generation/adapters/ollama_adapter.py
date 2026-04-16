"""Ollama Provider Adapter - Infrastructure layer implementation"""
from typing import Optional
from openai import AsyncOpenAI

from core.interfaces.llm_port import (
    ILLMPort, LLMRequest, LLMResponse, LLMUsage,
    LLMConnectionError, LLMRateLimitError, LLMResponseError
)


class OllamaAdapter(ILLMPort):
    """Ollama adapter using OpenAI-compatible API
    
    Ollama already provides async API, so this is a thin wrapper.
    """
    
    def __init__(self, base_url: str, default_model: str):
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama"  # Ollama doesn't require API key
        )
        self._default_model = default_model
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate content with Ollama (already async)"""
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt}
        ]
        
        # Ollama-specific: JSON mode and repetition penalty
        extra_params = {}
        if request.response_format == "json":
            extra_params["response_format"] = {"type": "json_object"}
            # JSON generation requires lower frequency_penalty to allow structured keywords
            # (e.g., "title", "description") to be repeated as needed
            extra_params["frequency_penalty"] = 0.5
        else:
            # Regular dialogue generation: higher penalty to prevent repetition
            # Note: Ollama's frequency_penalty implementation differs from OpenAI
            # Values > 1.0 can cause empty responses. Use conservative 0.8-1.0 range.
            # 0.0 = no penalty, 1.0 = moderate penalty, >1.0 = aggressive (risky)
            extra_params["frequency_penalty"] = 0.9
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=request.model or self._default_model,
                    messages=messages,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    **extra_params
                )
                
                # Extract response
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                
                # Validate response content (critical: prevent downstream JSON parse errors)
                if not content or not content.strip():
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(
                        f"Ollama returned empty response. "
                        f"finish_reason={finish_reason}, "
                        f"model={request.model or self._default_model}, "
                        f"max_tokens={request.max_tokens}, "
                        f"temperature={request.temperature}, "
                        f"frequency_penalty={extra_params.get('frequency_penalty', 'N/A')}"
                    )
                    raise LLMResponseError(
                        f"Ollama returned empty response (finish_reason={finish_reason}). "
                        f"Possible causes: (1) model not loaded or crashed, "
                        f"(2) max_tokens too low (current: {request.max_tokens}), "
                        f"(3) frequency_penalty issue (current: {extra_params.get('frequency_penalty', 'N/A')}). "
                        f"Check Ollama server logs for details."
                    )
                
                usage = LLMUsage(
                    provider="ollama",
                    model_name=request.model or self._default_model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    request_count=1
                )
                
                return LLMResponse(
                    content=content,  # Guaranteed non-empty by validation above
                    usage=usage,
                    finish_reason=finish_reason,
                    raw_response=response
                )
                
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                
                if "connection" in error_msg or "timeout" in error_msg:
                    if attempt < max_retries - 1:
                        import asyncio
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise LLMConnectionError(f"Ollama connection error: {e}") from e
                
                raise LLMResponseError(f"Ollama API error: {e}") from e
        
        raise LLMConnectionError(f"Max retries exceeded: {last_error}")
    
    async def health_check(self) -> bool:
        """Check Ollama API availability (connection check only, ignores empty responses)"""
        try:
            # Direct API call to check connection (bypass empty response validation)
            messages = [
                {"role": "system", "content": "Test"},
                {"role": "user", "content": "Reply with 'OK'"}
            ]
            response = await self._client.chat.completions.create(
                model=self._default_model,
                messages=messages,
                max_tokens=10,
                temperature=0.0
            )
            # Connection successful even if response is empty
            return True
        except Exception:
            return False
    
    @property
    def provider_name(self) -> str:
        return "ollama"
    
    @property
    def model_name(self) -> str:
        return self._default_model
