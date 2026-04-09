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
        
        # Ollama-specific: JSON mode
        extra_params = {}
        if request.response_format == "json":
            extra_params["response_format"] = {"type": "json_object"}
        
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
                usage = LLMUsage(
                    provider="ollama",
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
        """Check Ollama API availability"""
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
        return "ollama"
    
    @property
    def model_name(self) -> str:
        return self._default_model
