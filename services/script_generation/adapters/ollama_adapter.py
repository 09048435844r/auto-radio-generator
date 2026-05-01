"""Ollama Provider Adapter - Infrastructure layer implementation"""
import logging
from typing import Optional
from openai import AsyncOpenAI

from core.interfaces.llm_port import (
    ILLMPort, LLMRequest, LLMResponse, LLMUsage,
    LLMConnectionError, LLMRateLimitError, LLMResponseError
)

logger = logging.getLogger(__name__)

# 2026-05-02: thinking mode のローカルモデル（qwen3:32b 等）は content=None を返し、
# 本文を message.reasoning_content または OpenAI SDK の model_extra に格納するケースがある。
# 探索順序: 公式フィールド reasoning_content → 追加プロパティ群（thinking / thought）。
_THINKING_FALLBACK_KEYS = ("reasoning_content", "thinking", "thought")


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
                message = response.choices[0].message
                content = message.content
                finish_reason = response.choices[0].finish_reason

                # 2026-05-02: thinking mode の qwen3:32b 等は content=None を返し、本文を
                # reasoning_content / model_extra に格納するケースがある（本運用で
                # MetadataGenerator が下流で 'NoneType is not subscriptable' で落ちた
                # 実績あり）。content が None のときに限り、これらのフィールドから
                # フォールバックで取り出す。フォールバックが発動したことは warning で記録。
                if content is None:
                    fallback_source: Optional[str] = None
                    fallback_value: Optional[str] = None

                    # 公式フィールド reasoning_content を最優先（Pydantic モデルの属性）
                    direct = getattr(message, "reasoning_content", None)
                    if isinstance(direct, str) and direct.strip():
                        fallback_source = "message.reasoning_content"
                        fallback_value = direct

                    # 次に OpenAI SDK の model_extra（未マップ追加プロパティ）を順に探索
                    if fallback_value is None:
                        extra = getattr(message, "model_extra", None)
                        if isinstance(extra, dict):
                            for key in _THINKING_FALLBACK_KEYS:
                                value = extra.get(key)
                                if isinstance(value, str) and value.strip():
                                    fallback_source = f"message.model_extra[{key!r}]"
                                    fallback_value = value
                                    break

                    if fallback_value is not None:
                        logger.warning(
                            "Ollama content=None; falling back to %s (%d chars). "
                            "model=%s, finish_reason=%s. "
                            "thinking-mode model 等で content が空になる既知症状。",
                            fallback_source,
                            len(fallback_value),
                            request.model or self._default_model,
                            finish_reason,
                        )
                        content = fallback_value

                # Validate response content (critical: prevent downstream JSON parse errors)
                if not content or not content.strip():
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
