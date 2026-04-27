"""実行ログデータモデル

動画生成プロセスの完全な記録を保持するためのモデル。
YouTubeアナリティクス連携による台本改善の基盤データとして使用。
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from uuid import uuid4


class PromptRecord(BaseModel):
    """APIへのプロンプト送信記録"""
    phase: str = Field(..., description="Phase name: planning|research|scripting|metadata")
    api_provider: str = Field(..., description="gemini|perplexity")
    model_name: str = Field(..., description="実際に使用されたモデル名 (e.g., gemini-2.0-flash, sonar-pro)")
    system_prompt: Optional[str] = Field(None, description="System prompt text")
    user_prompt: str = Field(..., description="User prompt text")
    raw_response: str = Field(..., description="Raw API response (JSON string or text)")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ConfigSnapshot(BaseModel):
    """実行時の設定スナップショット（再現性確保用）"""
    yaml_config: Dict[str, Any] = Field(..., description="Serialized config.yaml")
    ui_overrides: Dict[str, Any] = Field(default_factory=dict, description="UIOverrides as dict")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Relevant env vars (API keys masked)")


class ExecutionLogEntry(BaseModel):
    """1回の動画生成プロセス全体の実行記録"""
    # Identity
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    app_version: str = Field(..., description="システムバージョン (e.g., v3.3.2)")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    output_directory: str = Field(..., description="e.g., output/20260220_190000")
    
    # Input
    theme: str = Field(..., description="User-provided theme")
    config_snapshot: ConfigSnapshot
    
    # Process
    prompts: List[PromptRecord] = Field(default_factory=list)
    
    # Output
    generated_files: Dict[str, str] = Field(
        default_factory=dict,
        description="File paths: {script, video, audio, subtitle, thumbnail, metadata}"
    )
    
    # Outcome
    success: bool = Field(..., description="Whether workflow completed successfully")
    error_message: Optional[str] = Field(None)
    total_duration_sec: float = Field(0.0)
    perplexity_requests: int = Field(0, description="Number of Perplexity API requests made in this execution (including failures)")
