"""Execution Context - Immutable context propagation"""
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime
import uuid

from core.models import AppConfig


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable execution context for workflow
    
    Contains all contextual information needed throughout the workflow,
    propagated from UI layer to the deepest domain components.
    """
    # Provider selection
    provider: str  # "gemini" | "openai" | "anthropic" | "ollama"
    
    # Configuration
    config: AppConfig
    
    # Callbacks (optional)
    log_callback: Optional[Callable[[str], None]] = None
    progress_callback: Optional[Callable[[float, str], None]] = None
    
    # Feature flags
    use_orchestrator: bool = True
    enable_research: bool = True
    
    # Session metadata
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    
    def log(self, message: str) -> None:
        """Safe logging with callback"""
        if self.log_callback:
            self.log_callback(message)
    
    def progress(self, value: float, message: str) -> None:
        """Safe progress reporting with callback"""
        if self.progress_callback:
            self.progress_callback(value, message)
    
    def with_provider(self, provider: str) -> "ExecutionContext":
        """Create new context with different provider (immutable)"""
        return ExecutionContext(
            provider=provider,
            config=self.config,
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            use_orchestrator=self.use_orchestrator,
            enable_research=self.enable_research,
            session_id=self.session_id,
            timestamp=self.timestamp
        )
