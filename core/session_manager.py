"""セッション管理モジュール

パイプライン分離アーキテクチャにおけるセッション単位のファイルI/Oを管理する。
workspace/{session_id}/ 配下での中間成果物の保存・読み込みを担当。
"""
from pathlib import Path
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.models.artifacts import ResearchBrief
    from core.models.script import RadioScriptArtifact
    from core.models.curation import CurationResult
    from core.models.show_plan import ShowPlan


class SessionManager:
    """セッション管理クラス
    
    workspace/{session_id}/配下でのファイルI/Oを管理する。
    各フェーズの中間成果物を永続化し、フェーズ単位での実行・再開を可能にする。
    """
    
    def __init__(self, project_root: Path, session_id: Optional[str] = None):
        """Initialize SessionManager
        
        Args:
            project_root: Project root directory
            session_id: Session ID (if None, create new session with timestamp)
        """
        self.project_root = Path(project_root)
        self.workspace_root = self.project_root / "workspace"
        
        # Create new session if session_id is None or empty string
        if session_id is None or session_id == "":
            # Create new session with timestamp
            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        else:
            self.session_id = session_id
        
        self.session_dir = self.workspace_root / self.session_id
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            # Already created by another process, safe to ignore
            pass
    
    def get_research_brief_path(self) -> Path:
        """Get path to ResearchBrief file"""
        return self.session_dir / "research_brief.json"
    
    def get_script_artifact_path(self) -> Path:
        """Get path to RadioScriptArtifact file"""
        return self.session_dir / "script_artifact.json"
    
    def get_audio_dir(self) -> Path:
        """Get audio output directory"""
        audio_dir = self.session_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        return audio_dir
    
    def get_video_dir(self) -> Path:
        """Get video output directory"""
        video_dir = self.session_dir / "videos"
        video_dir.mkdir(exist_ok=True)
        return video_dir
    
    def get_logs_dir(self) -> Path:
        """Get logs directory"""
        logs_dir = self.session_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        return logs_dir
    
    def save_research_brief(self, brief: "ResearchBrief") -> Path:
        """Save ResearchBrief to file
        
        Args:
            brief: ResearchBrief instance
            
        Returns:
            Path to saved file
        """
        path = self.get_research_brief_path()
        path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
        return path
    
    def load_research_brief(self) -> "ResearchBrief":
        """Load ResearchBrief from file
        
        Returns:
            ResearchBrief instance
            
        Raises:
            FileNotFoundError: If research_brief.json does not exist
        """
        from core.models.artifacts import ResearchBrief
        
        path = self.get_research_brief_path()
        if not path.exists():
            raise FileNotFoundError(
                f"ResearchBrief not found: {path}\n"
                f"Please run research phase first: python main.py --phase research --theme 'your theme'"
            )
        
        return ResearchBrief.model_validate_json(path.read_text(encoding="utf-8"))
    
    def save_script_artifact(self, artifact: "RadioScriptArtifact") -> Path:
        """Save RadioScriptArtifact to file
        
        Args:
            artifact: RadioScriptArtifact instance
            
        Returns:
            Path to saved file
        """
        path = self.get_script_artifact_path()
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return path
    
    def load_script_artifact(self) -> "RadioScriptArtifact":
        """Load RadioScriptArtifact from file
        
        Returns:
            RadioScriptArtifact instance
            
        Raises:
            FileNotFoundError: If script_artifact.json does not exist
        """
        from core.models.script import RadioScriptArtifact
        
        path = self.get_script_artifact_path()
        if not path.exists():
            raise FileNotFoundError(
                f"RadioScriptArtifact not found: {path}\n"
                f"Please run scripting phase first: python main.py --phase script --session {self.session_id}"
            )
        
        return RadioScriptArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    
    def has_research_brief(self) -> bool:
        """Check if ResearchBrief exists"""
        return self.get_research_brief_path().exists()
    
    def has_script_artifact(self) -> bool:
        """Check if RadioScriptArtifact exists"""
        return self.get_script_artifact_path().exists()

    # ------------------------------------------------------------------
    # CurationResult persistence (Phase 2 HITL 施策⑤)
    # ------------------------------------------------------------------

    def get_curation_result_path(self) -> Path:
        """Get path to CurationResult file (human-editable topic selection)."""
        return self.session_dir / "curation_result.json"

    def save_curation_result(self, curation: "CurationResult") -> Path:
        """Save CurationResult to file (typically after human editing in HITL).

        Args:
            curation: CurationResult instance

        Returns:
            Path to saved file
        """
        path = self.get_curation_result_path()
        path.write_text(curation.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_curation_result(self) -> "CurationResult":
        """Load CurationResult from file.

        Returns:
            CurationResult instance

        Raises:
            FileNotFoundError: If curation_result.json does not exist
        """
        from core.models.curation import CurationResult

        path = self.get_curation_result_path()
        if not path.exists():
            raise FileNotFoundError(
                f"CurationResult not found: {path}\n"
                f"Please run curation phase first (Gate 2a in HITL)."
            )
        return CurationResult.model_validate_json(path.read_text(encoding="utf-8"))

    def has_curation_result(self) -> bool:
        """Check if CurationResult exists (i.e., user already ran Gate 2a)."""
        return self.get_curation_result_path().exists()

    # ------------------------------------------------------------------
    # ShowPlan persistence (Phase 3 施策④)
    # ------------------------------------------------------------------

    def get_show_plan_path(self) -> Path:
        """Get path to ShowPlan file (番組構成プラン)."""
        return self.session_dir / "show_plan.json"

    def save_show_plan(self, show_plan: "ShowPlan") -> Path:
        """Save ShowPlan to file.

        Args:
            show_plan: ShowPlan instance

        Returns:
            Path to saved file
        """
        path = self.get_show_plan_path()
        path.write_text(show_plan.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_show_plan(self) -> "ShowPlan":
        """Load ShowPlan from file.

        Returns:
            ShowPlan instance

        Raises:
            FileNotFoundError: If show_plan.json does not exist
        """
        from core.models.show_plan import ShowPlan

        path = self.get_show_plan_path()
        if not path.exists():
            raise FileNotFoundError(
                f"ShowPlan not found: {path}\n"
                f"Please run ShowRunner (Phase 3) first."
            )
        return ShowPlan.model_validate_json(path.read_text(encoding="utf-8"))

    def has_show_plan(self) -> bool:
        """Check if ShowPlan exists in this session."""
        return self.get_show_plan_path().exists()

    def get_session_status(self) -> dict:
        """Get current session status
        
        Returns:
            Dictionary with phase completion status
        """
        return {
            "session_id": self.session_id,
            "session_dir": str(self.session_dir),
            "research_completed": self.has_research_brief(),
            "curation_completed": self.has_curation_result(),
            "show_plan_completed": self.has_show_plan(),
            "scripting_completed": self.has_script_artifact(),
        }
