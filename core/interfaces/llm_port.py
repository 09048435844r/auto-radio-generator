"""LLM Port Interface - Domain layer abstraction for LLM communication"""
from abc import ABC, abstractmethod
from typing import Optional, Any
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
