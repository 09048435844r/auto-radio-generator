"""Gemini Provider Adapter - Infrastructure layer implementation"""
import asyncio
import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types

from core.interfaces.llm_port import (
    ILLMPort, LLMRequest, LLMResponse, LLMUsage,
    LLMConnectionError, LLMRateLimitError, LLMResponseError
)


class GeminiAdapter(ILLMPort):
    """Gemini SDK adapter with async wrapper
    
    Responsibilities:
    1. Wrap synchronous Gemini SDK in async interface
    2. Translate Gemini-specific errors to abstract port errors
    3. Handle Gemini-specific quirks (safety settings, response format)
    4. Ensure non-blocking execution via run_in_executor
    """
    
    def __init__(self, api_key: str, default_model: str):
        self._client = genai.Client(api_key=api_key)
        self._default_model = default_model
        self._safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        ]
        # Bounded thread pool to prevent unlimited thread spawning
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="gemini-")
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate content with Gemini (async wrapper)"""
        # Run synchronous SDK call in thread pool to avoid blocking
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,  # Use bounded thread pool
            self._generate_sync,
            request
        )
    
    def _generate_sync(self, request: LLMRequest) -> LLMResponse:
        """Synchronous Gemini API call (runs in thread pool)"""
        config_params = {
            "max_output_tokens": request.max_tokens,
            "temperature": request.temperature,
            "safety_settings": self._safety_settings,
        }
        
        # Gemini-specific: JSON mode handling
        # Note: response_mime_type can cause truncation, use text mode
        if request.response_format == "json":
            pass  # Use text mode and parse JSON manually
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = self._client.models.generate_content(
                    model=request.model or self._default_model,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part(text=f"{request.system_prompt}\n\n{request.user_prompt}")]
                        )
                    ],
                    config=types.GenerateContentConfig(**config_params)
                )
                
                # Extract response
                content = response.text
                finish_reason = self._extract_finish_reason(response)
                usage = self._extract_usage(response, request.model)
                
                return LLMResponse(
                    content=content,
                    usage=usage,
                    finish_reason=finish_reason,
                    raw_response=response
                )
                
            except Exception as e:
                last_error = e
                
                # Check for HTTP status codes (more reliable than string matching)
                status_code = getattr(e, 'status_code', None) or getattr(getattr(e, 'response', None), 'status_code', None)
                
                # Rate limit errors (429, 503)
                if status_code in (429, 503):
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    raise LLMRateLimitError(f"Gemini rate limit (HTTP {status_code}): {e}") from e
                
                # Connection errors - check exception type first, then fallback to string matching
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ["connection", "timeout", "disconnected", "network"]):
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    raise LLMConnectionError(f"Gemini connection error: {e}") from e
                
                # Check for quota/rate limit in message as fallback
                if any(keyword in error_msg for keyword in ["rate", "quota", "limit"]):
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    raise LLMRateLimitError(f"Gemini rate limit: {e}") from e
                
                # Unknown error
                raise LLMResponseError(f"Gemini API error: {e}") from e
        
        raise LLMConnectionError(f"Max retries exceeded: {last_error}")
    
    def _extract_finish_reason(self, response) -> str:
        """Extract finish reason from Gemini response"""
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            reason = getattr(candidate, "finish_reason", None)
            if reason:
                reason_str = str(reason)
                if "STOP" in reason_str:
                    return "stop"
                elif "MAX_TOKENS" in reason_str or "LENGTH" in reason_str:
                    return "length"
                elif "SAFETY" in reason_str or "RECITATION" in reason_str:
                    # Safety blocks and recitations should be treated as errors
                    return "error"
        return "stop"
    
    def _extract_usage(self, response, model_name: str) -> LLMUsage:
        """Extract usage from Gemini response"""
        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata:
            return LLMUsage(
                provider="gemini",
                model_name=model_name or self._default_model,
                input_tokens=getattr(usage_metadata, "prompt_token_count", 0),
                output_tokens=getattr(usage_metadata, "candidates_token_count", 0),
                request_count=1
            )
        return LLMUsage(provider="gemini", model_name=model_name or self._default_model, request_count=1)
    
    async def health_check(self) -> bool:
        """Check Gemini API availability"""
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
        return "gemini"
    
    @property
    def model_name(self) -> str:
        return self._default_model
