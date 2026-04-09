"""LLM Adapter Factory - Creates provider-specific adapters"""
from typing import Optional, Literal
from core.interfaces.llm_port import ILLMPort
from core.models import AppConfig

# Type alias for supported providers
ProviderType = Literal["gemini", "openai", "anthropic", "ollama"]


class LLMAdapterFactory:
    """Factory for creating provider-specific LLM adapters
    
    Centralizes adapter creation logic and provider selection.
    """
    
    @staticmethod
    def create(
        config: AppConfig,
        provider: ProviderType,
        model_override: Optional[str] = None
    ) -> ILLMPort:
        """Create LLM adapter for specified provider
        
        Args:
            config: Application configuration
            provider: Provider name ("gemini" | "openai" | "anthropic" | "ollama")
            model_override: Optional model name override
            
        Returns:
            ILLMPort implementation for the provider
            
        Raises:
            ValueError: If provider is invalid or API key is missing
        """
        provider = provider.lower()
        
        if provider == "gemini":
            from .gemini_adapter import GeminiAdapter
            api_key = config.env.gemini_api_key
            if not api_key:
                raise ValueError("GEMINI_API_KEY not configured")
            model = model_override or config.yaml.script_generator.gemini.model
            return GeminiAdapter(api_key=api_key, default_model=model)
        
        elif provider == "openai":
            from .openai_adapter import OpenAIAdapter
            api_key = config.env.openai_api_key
            if not api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            model = model_override or config.yaml.script_generator.openai.model
            return OpenAIAdapter(api_key=api_key, default_model=model)
        
        elif provider == "anthropic":
            from .anthropic_adapter import AnthropicAdapter
            api_key = config.env.anthropic_api_key
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            model = model_override or config.yaml.script_generator.anthropic.model
            return AnthropicAdapter(api_key=api_key, default_model=model)
        
        elif provider == "ollama":
            from .ollama_adapter import OllamaAdapter
            base_url = config.yaml.script_generator.ollama.base_url
            model = model_override or config.yaml.script_generator.ollama.model
            return OllamaAdapter(base_url=base_url, default_model=model)
        
        else:
            available = ["gemini", "openai", "anthropic", "ollama"]
            raise ValueError(
                f"Invalid provider: {provider}. Available: {', '.join(available)}"
            )
