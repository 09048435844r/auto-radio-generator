"""パイプライン分離サービス

各フェーズを独立実行可能なサービスとして提供する。
Step 3 (2026-05-09): 外部台本モード用 phase を追加。
"""
from services.pipeline.research_phase import execute_research_phase
from services.pipeline.scripting_phase import execute_scripting_phase, execute_curation_only
from services.pipeline.production_phase import execute_production_phase
from services.pipeline.external_script_phase import (
    execute_external_script_phase,
    ExternalScriptPhaseResult,
)

__all__ = [
    "execute_research_phase",
    "execute_curation_only",
    "execute_scripting_phase",
    "execute_production_phase",
    "execute_external_script_phase",
    "ExternalScriptPhaseResult",
]
