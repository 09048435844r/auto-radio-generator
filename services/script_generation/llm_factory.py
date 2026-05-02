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
        provider: Provider name ("gemini" | "openai" | "anthropic" | "ollama")
    
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
    
    elif provider == "ollama":
        from .ollama_client import OllamaClient
        return OllamaClient(config)
    
    else:
        available = ["gemini", "openai", "anthropic", "ollama"]
        raise ValueError(
            f"Invalid provider: {provider}. Available: {', '.join(available)}"
        )


def get_provider_from_model_name(model_name: str) -> str:
    """Infer provider name from model name

    Args:
        model_name: Model name (e.g., "gpt-5.4", "gemini-3.1-pro", "claude-sonnet-4.6",
                    "gpt-oss:20b-long", "qwen3-next-80b")

    Returns:
        str: Provider name ("gemini" | "openai" | "anthropic" | "ollama")

    Raises:
        ValueError: If unknown model name
    """
    if model_name.startswith("gemini-"):
        return "gemini"
    elif model_name.startswith(("gpt-", "o1-", "o3-")):
        return "openai"
    elif model_name.startswith("claude-"):
        return "anthropic"
    elif model_name.startswith(("gpt-oss:", "llama3.", "phi3:", "mistral:", "mixtral:", "qwen")):
        # 2026-05-03: vLLM 経由でホストされる qwen 系（qwen3-next-80b / qwen3:32b /
        # qwen2.5-coder:32b 等）を Ollama provider にマッピング。OllamaAdapter は
        # OpenAI 互換 API を叩くだけなので vLLM サーバーでも動作する。
        return "ollama"
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
    
    # Ollama is always available (local server, no API key needed)
    available.append("ollama")
    
    return available


def get_available_models(config: AppConfig) -> list[str]:
    """Get list of available models (only for providers with API keys configured)
    
    Args:
        config: Application configuration
    
    Returns:
        list[str]: List of available model names
    """
    # Get all models from AppConfig (SSOT)
    from services.cost_calculator import CostCalculator
    
    calculator = CostCalculator(config)
    all_models = calculator.get_all_available_models()
    
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
