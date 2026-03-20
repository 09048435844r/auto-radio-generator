"""LLM Provider Factory

Factory pattern for creating script generation clients based on provider name.
"""
from typing import Optional
from pathlib import Path
import yaml
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


def get_provider_from_model_name(model_name: str) -> str:
    """Infer provider name from model name
    
    Args:
        model_name: Model name (e.g., "gpt-4o-mini", "gemini-1.5-pro")
    
    Returns:
        str: Provider name ("gemini" | "openai" | "anthropic")
    
    Raises:
        ValueError: If unknown model name
    """
    if model_name.startswith("gemini-"):
        return "gemini"
    elif model_name.startswith(("gpt-", "o1-")):
        return "openai"
    elif model_name.startswith("claude-"):
        return "anthropic"
    else:
        raise ValueError(f"Unknown model name: {model_name}")


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


def get_available_models(config: AppConfig) -> list[str]:
    """Get list of available models (only for providers with API keys configured)
    
    Args:
        config: Application configuration
    
    Returns:
        list[str]: List of available model names
    """
    # Load model list from costs.yaml
    costs_path = Path(__file__).parent.parent.parent / "config" / "costs.yaml"
    with open(costs_path, "r", encoding="utf-8") as f:
        costs = yaml.safe_load(f)
    
    all_models = list(costs["llm_models"].keys())
    
    # Return only models for providers with API keys configured
    available_providers = get_available_providers(config)
    available_models = []
    
    for model in all_models:
        try:
            provider = get_provider_from_model_name(model)
            if provider in available_providers:
                available_models.append(model)
        except ValueError:
            continue
    
    return available_models
