"""Ollama Provider Adapter - Infrastructure layer implementation

Step 4 v2 (2026-05-10) @deprecated: 旧 Gemini 自動経路の provider-agnostic 構成要素として
残置。HITL 経路でのみ呼ばれる。Step 5 で再評価予定。
"""
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
    
    def __init__(self, base_url: str, default_model: str, inject_no_think: bool = True):
        # 2026-07: inject_no_think は DeepSeekV4Flash 移行対応のオプトアウト。
        # /no_think は Qwen3 系 chat template 専用の制御トークンで、DeepSeek には
        # ただのリテラルとして届きプロンプト汚染になる。デフォルト True は
        # 既存挙動（Qwen 系バックエンド）の完全維持のため。
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama"  # Ollama doesn't require API key
        )
        self._default_model = default_model
        self._inject_no_think = inject_no_think
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate content with Ollama (already async)"""
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt}
        ]

        # 2026-05-06: thinking mode 抑制の二重対策。chat_template_kwargs.enable_thinking
        # だけでは Qwen3.5-122B が JSON 内に思考の断片を混入させる本運用バグの実績
        # があるため、system プロンプトの先頭に /no_think トークンも付与する。
        # これは Qwen3 系の chat template が解釈する制御トークンで、prompt-level で
        # thinking を確実に無効化できる。enable_thinking=True の時は付与しない。
        # 2026-07: inject_no_think=False（DeepSeek 等 Qwen 以外のバックエンド）の
        # 場合も付与しない。thinking 抑制は Proxy 側 reasoning_effort で担保。
        if self._inject_no_think and not request.enable_thinking:
            system_msg_found = False
            for msg in messages:
                if msg["role"] == "system":
                    msg["content"] = "/no_think\n" + msg["content"]
                    system_msg_found = True
                    break
            if not system_msg_found:
                # 防御的: 何らかの理由で system メッセージが無い場合は先頭に追加
                messages.insert(0, {"role": "system", "content": "/no_think"})

        # Ollama-specific: JSON mode and repetition penalty
        extra_params = {}
        if request.response_schema is not None:
            # 2026-05-06: vLLM Structured Output (OpenAI 標準形式)。
            # response_schema を渡された場合は response_format=json_schema で
            # vLLM 側に schema 制約付き生成を依頼する。enum / required / 型を強制し、
            # JSON 切断や型ミスマッチによる Pydantic ValidationError を根治。
            # 実機検証 (vLLM 0.20.0 / Qwen3.5-122B-A10B-NVFP4) で
            # extra_body.guided_json は無効、本形式のみが拘束を効かせると確認済み。
            extra_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_schema_name,
                    "strict": request.response_schema_strict,
                    "schema": request.response_schema,
                },
            }
            # JSON 生成と同等のキーワード反復許容
            extra_params["frequency_penalty"] = 0.5
        elif request.response_format == "json":
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

        # 2026-05-06: vLLM (Qwen3.5 thinking model) 対策。
        # vLLM は chat_template_kwargs.enable_thinking=False を受け取ると、thinking
        # token を生成せず可視メッセージだけを返す。これが無いと thinking token で
        # max_tokens を食い潰し finish_reason="length" + 空 content で落ちる。
        # Ollama 本体は未知の extra_body フィールドを無視するため、無害に共存する。
        extra_body = {
            "chat_template_kwargs": {
                "enable_thinking": request.enable_thinking,
            }
        }

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=request.model or self._default_model,
                    messages=messages,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    extra_body=extra_body,
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
