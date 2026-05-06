"""LLM Port Interface - Domain layer abstraction for LLM communication"""
from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
from dataclasses import dataclass
from core.models import LLMUsage


@dataclass(frozen=True)
class LLMRequest:
    """Immutable LLM request value object"""
    system_prompt: str
    user_prompt: str
    model: str
    max_tokens: int
    temperature: float
    response_format: str = "json"  # "json" | "text"
    # 2026-05-06: vLLM (Qwen3.5 thinking model) で thinking token が max_tokens を
    # 食い潰し、可視メッセージが空のまま finish_reason="length" で返る本運用バグの
    # 対策として、Ollama OpenAI 互換経路（vLLM 含む）には extra_body 経由で
    # chat_template_kwargs.enable_thinking を付与する。
    # 既定 False。将来エージェント別に thinking を有効化する場合は LLMRequest 構築
    # 時に True を渡せる構造（純粋な追加パラメータ。他プロバイダーは無視可能）。
    enable_thinking: bool = False

    # 2026-05-06: vLLM Structured Output (response_format=json_schema) 対応。
    # Pydantic の model_json_schema() 出力をそのまま渡すと OllamaAdapter が
    # OpenAI 標準形式の `response_format={"type":"json_schema", "json_schema":{...}}`
    # に変換し、vLLM が schema 制約付きの JSON を返す（enum / required / 型を強制）。
    # 既定 None で完全な後方互換（既存呼び出しは挙動不変、json_object モードを維持）。
    # 他プロバイダー (Gemini / OpenAI / Anthropic) のアダプタは本フィールドを
    # 「対応していなければ無視」する契約 — frozen dataclass なので追加は破壊的でない。
    response_schema: Optional[Dict[str, Any]] = None
    response_schema_name: str = "response"
    response_schema_strict: bool = False

    def __post_init__(self):
        """Validate request parameters"""
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                f"temperature must be between 0.0 and 2.0 (got {self.temperature}). "
                "Note: Some providers (e.g., Gemini) may only support 0.0-1.0. "
                "Use 0.0-1.0 for maximum cross-provider compatibility."
            )


@dataclass(frozen=True)
class LLMResponse:
    """Immutable LLM response value object"""
    content: str
    usage: LLMUsage
    finish_reason: str  # "stop" | "length" | "error"
    raw_response: Optional[Any] = None  # For debugging only


class ILLMPort(ABC):
    """Port interface for LLM communication
    
    This interface represents the domain's needs for LLM interaction,
    completely decoupled from any specific provider implementation.
    All methods are async to ensure non-blocking behavior.
    """
    
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate content using LLM
        
        Args:
            request: Immutable request value object
            
        Returns:
            Immutable response value object
            
        Raises:
            LLMPortError: Abstract error for all LLM-related failures
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM service is available"""
        pass
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get provider name for logging and cost calculation"""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get current model name"""
        pass


class LLMPortError(Exception):
    """Base exception for all LLM port errors"""
    pass


class LLMConnectionError(LLMPortError):
    """Connection-related errors (retryable)"""
    pass


class LLMRateLimitError(LLMPortError):
    """Rate limit errors (retryable with backoff)"""
    pass


class LLMValidationError(LLMPortError):
    """Request validation errors (non-retryable)"""
    pass


class LLMResponseError(LLMPortError):
    """Response parsing/validation errors"""
    pass
