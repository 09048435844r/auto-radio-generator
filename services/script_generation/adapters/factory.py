"""LLM Adapter Factory - Creates provider-specific adapters

Step 4 v2 (2026-05-10): "gemini" provider は削除。OpenAI / Anthropic / Ollama のみ
サポート。
"""
from typing import Optional, Literal
from core.interfaces.llm_port import ILLMPort
from core.models import AppConfig

# Type alias for supported providers
ProviderType = Literal["openai", "anthropic", "ollama"]


class LLMAdapterFactory:
    """Factory for creating provider-specific LLM adapters

    Centralizes adapter creation logic and provider selection.
    Step 4 v2: "gemini" branch は削除。
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
            provider: Provider name ("openai" | "anthropic" | "ollama")
            model_override: Optional model name override

        Returns:
            ILLMPort implementation for the provider

        Raises:
            ValueError: If provider is invalid or API key is missing
        """
        provider = provider.lower()

        if provider == "openai":
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
            ollama_cfg = config.yaml.script_generator.ollama
            base_url = ollama_cfg.base_url
            model = model_override or ollama_cfg.model
            # 2026-07: DeepSeekV4Flash 移行。/no_think 注入可否を config から配線
            # （デフォルト True = 旧挙動。shipped config.yaml は false を明示）。
            inject_no_think = getattr(ollama_cfg, "inject_no_think", True)
            return OllamaAdapter(
                base_url=base_url,
                default_model=model,
                inject_no_think=inject_no_think,
            )

        elif provider == "gemini":
            # Step 4 v2: Gemini adapter は物理削除済み
            raise ValueError(
                "Step 4 v2 (2026-05-10): 'gemini' provider は削除されました。"
                "外部台本モード (services/pipeline/external_script_phase.py) を使用してください。"
            )

        else:
            available = ["openai", "anthropic", "ollama"]
            raise ValueError(
                f"Invalid provider: {provider}. Available: {', '.join(available)}"
            )
