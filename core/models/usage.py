"""API使用量とコスト計算のデータモデル"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PerplexityUsage:
    """Perplexity API使用量"""
    request_count: int = 0
    
    def __add__(self, other: "PerplexityUsage") -> "PerplexityUsage":
        return PerplexityUsage(
            request_count=self.request_count + other.request_count
        )


@dataclass
class LLMUsage:
    """Generic LLM API usage with provider tracking
    
    Supports multiple LLM providers (Gemini, OpenAI, Anthropic) with
    provider-specific tracking for accurate cost calculation.
    """
    provider: str  # "gemini" | "openai" | "anthropic"
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
    
    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        """Add two LLMUsage objects (must be same provider)"""
        if self.provider != other.provider:
            raise ValueError(f"Cannot add LLMUsage from different providers: {self.provider} vs {other.provider}")
        return LLMUsage(
            provider=self.provider,
            model_name=self.model_name or other.model_name,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            request_count=self.request_count + other.request_count
        )


# Backward compatibility alias
GeminiUsage = LLMUsage


@dataclass
class VoicevoxUsage:
    """VOICEVOX使用量（ローカル実行のため無料）"""
    phrase_count: int = 0
    total_duration_sec: float = 0.0


@dataclass
class TotalUsage:
    """Total API usage aggregation with multi-provider support
    
    Aggregates usage across all API providers. LLM usage is tracked
    per-provider in a dictionary to prevent information loss when
    multiple providers are used in a single workflow.
    """
    perplexity: PerplexityUsage = field(default_factory=PerplexityUsage)
    llm_usage: dict[str, LLMUsage] = field(default_factory=dict)
    voicevox: VoicevoxUsage = field(default_factory=VoicevoxUsage)
    
    # Duration tracking
    research_duration_sec: float = 0.0
    script_duration_sec: float = 0.0
    audio_duration_sec: float = 0.0
    render_duration_sec: float = 0.0
    total_duration_sec: float = 0.0
    
    # Image generation time tracking
    segment_bg_generation_time: float = 0.0  # セグメント背景生成時間（秒）
    thumbnail_bg_generation_time: float = 0.0  # サムネイル背景生成時間（秒）
    
    @property
    def gemini(self) -> LLMUsage:
        """Backward compatibility property for existing code"""
        return self.llm_usage.get(
            "gemini",
            LLMUsage(
                provider="gemini",
                model_name="",
                input_tokens=0,
                output_tokens=0,
                request_count=0
            )
        )


@dataclass
class CostBreakdown:
    """コスト内訳"""
    perplexity_usd: float = 0.0
    gemini_input_usd: float = 0.0
    gemini_output_usd: float = 0.0
    voicevox_usd: float = 0.0  # 常に0
    
    total_usd: float = 0.0
    total_jpy: float = 0.0
    
    # 無料枠かどうか
    is_free_tier: bool = False
    free_tier_note: str = ""
