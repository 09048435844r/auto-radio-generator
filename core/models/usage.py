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
class GeminiUsage:
    """Gemini API使用量"""
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    model_name: str = ""
    
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
    
    def __add__(self, other: "GeminiUsage") -> "GeminiUsage":
        return GeminiUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            request_count=self.request_count + other.request_count,
            model_name=self.model_name or other.model_name
        )


@dataclass
class VoicevoxUsage:
    """VOICEVOX使用量（ローカル実行のため無料）"""
    phrase_count: int = 0
    total_duration_sec: float = 0.0


@dataclass
class TotalUsage:
    """全API使用量の集約"""
    perplexity: PerplexityUsage = field(default_factory=PerplexityUsage)
    gemini: GeminiUsage = field(default_factory=GeminiUsage)
    voicevox: VoicevoxUsage = field(default_factory=VoicevoxUsage)
    
    # 処理時間
    total_duration_sec: float = 0.0
    research_duration_sec: float = 0.0
    script_duration_sec: float = 0.0
    audio_duration_sec: float = 0.0
    render_duration_sec: float = 0.0


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
