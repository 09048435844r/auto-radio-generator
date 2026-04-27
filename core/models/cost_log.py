"""コスト履歴データモデル

API使用量とコストの記録を保持するためのモデル。
実行ログとexecution_idで紐付け、コスト分析・最適化に使用。
"""
from datetime import datetime
from pydantic import BaseModel, Field


class CostLogEntry(BaseModel):
    """1回の動画生成におけるコスト記録"""
    # Link to execution
    execution_id: str = Field(..., description="References ExecutionLogEntry.execution_id")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    output_directory: str = Field(..., description="e.g., output/20260220_190000")
    
    # API Usage (from TotalUsage)
    perplexity_requests: int = Field(0)
    perplexity_model_name: str = Field("", description="使用されたPerplexityモデル名")
    
    gemini_input_tokens: int = Field(0)
    gemini_output_tokens: int = Field(0)
    gemini_model_name: str = Field("", description="使用されたGeminiモデル名")
    
    voicevox_phrases: int = Field(0)
    voicevox_duration_sec: float = Field(0.0)
    
    # Costs (from CostBreakdown)
    perplexity_usd: float = Field(0.0)
    gemini_input_usd: float = Field(0.0)
    gemini_output_usd: float = Field(0.0)
    total_usd: float = Field(0.0)
    total_jpy: float = Field(0.0)
    is_free_tier: bool = Field(False)
    
    # Duration breakdown
    research_duration_sec: float = Field(0.0)
    script_duration_sec: float = Field(0.0)
    audio_duration_sec: float = Field(0.0)
    render_duration_sec: float = Field(0.0)
    total_duration_sec: float = Field(0.0)
