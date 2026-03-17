"""LLM Provider Factory

Factory pattern for creating script generation clients based on provider name.
"""
from typing import Optional
from rich.console import Console

from core.interfaces.script_generator import IScriptGenerator
from core.models import AppConfig

console = Console()


def create_script_generator(config: AppConfig, provider: str = "gemini") -> IScriptGenerator:
    """Create script generator client based on provider name
    
    Args:
        config: Application configuration
        provider: Provider name ("gemini" | "openai" | "anthropic")
    
    Returns:
        IScriptGenerator: Provider-specific client instance
    
    Raises:
        ValueError: If invalid provider name or missing API key
    """
    provider = provider.lower()
    console.print(f"[dim]Creating LLM client: {provider}[/dim]")
    
    if provider == "gemini":
        from .gemini_client import GeminiClient
        return GeminiClient(config)
    
    elif provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(config)
    
    elif provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(config)
    
    else:
        available = ["gemini", "openai", "anthropic"]
        raise ValueError(
            f"Invalid provider: {provider}. Available: {', '.join(available)}"
        )


def get_available_providers(config: AppConfig) -> list[str]:
    """Get list of available providers based on configured API keys
    
    Args:
        config: Application configuration
    
    Returns:
        list[str]: List of available provider names
    """
    available = []
    
    if hasattr(config.env, 'gemini_api_key') and config.env.gemini_api_key:
        available.append("gemini")
    
    if hasattr(config.env, 'openai_api_key') and config.env.openai_api_key:
        available.append("openai")
    
    if hasattr(config.env, 'anthropic_api_key') and config.env.anthropic_api_key:
        available.append("anthropic")
    
    return available
