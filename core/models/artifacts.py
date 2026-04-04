"""中間成果物のデータモデル

パイプライン分離アーキテクチャにおける各フェーズの入出力を定義する。
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ResearchBrief(BaseModel):
    """リサーチフェーズの出力成果物
    
    台本作成フェーズへの入力として使用される。
    各フェーズを独立実行可能にするための中間成果物。
    """
    # Metadata
    session_id: str = Field(..., description="Session ID (e.g., 20260404_065500)")
    theme: str = Field(..., description="Research theme")
    research_mode: str = Field(..., description="Research mode (debate/voices/trivia/lecture/weekly_digest)")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Creation timestamp")
    
    # Research results
    research_content: str = Field(..., description="Collected research content (full text)")
    research_sources: List[dict] = Field(
        default_factory=list,
        description="List of research sources (ResearchSource in dict format)"
    )
    
    # Planning information
    queries: List[str] = Field(..., description="List of executed search queries")
    angle: str = Field(..., description="Script angle/concept")
    
    # Curation results (when Orchestrator is enabled)
    curated_topics: Optional[List[dict]] = Field(
        None,
        description="Curated topics (CuratedTopic in dict format)"
    )
    
    # Usage and cost tracking
    perplexity_usage: Optional[dict] = Field(None, description="Perplexity API usage")
    gemini_usage_planning: Optional[dict] = Field(None, description="Gemini API usage for planning phase")
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "20260404_065500",
                "theme": "持続血糖測定器CGMについて",
                "research_mode": "lecture",
                "queries": ["CGMの仕組み", "CGMの精度", "CGMの活用事例"],
                "angle": "初心者向けに比喩を使って解説",
                "research_content": "...",
                "research_sources": []
            }
        }
