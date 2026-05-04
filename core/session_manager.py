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
    from core.models.fact_sheet import FactSheet
    from core.models.fact_check_report import FactCheckReport


class SessionManager:
    """セッション管理クラス
    
    workspace/{session_id}/配下でのファイルI/Oを管理する。
    各フェーズの中間成果物を永続化し、フェーズ単位での実行・再開を可能にする。
    """
    
    def __init__(
        self,
        project_root: Path,
        session_id: Optional[str] = None,
        session_dir: Optional[Path] = None,
    ):
        """Initialize SessionManager

        Args:
            project_root: Project root directory
            session_id: Session ID (if None, create new session with timestamp).
                        Ignored when `session_dir` is provided (derived from dir name instead).
            session_dir: Explicit session directory override. When provided, this path is
                        used verbatim instead of the default `project_root/workspace/{session_id}/`.
                        This allows the legacy Gradio auto mode (which writes to
                        `output/{timestamp}/`) to share the same SessionManager API with
                        HITL / CLI modes that write to `workspace/{session_id}/`.
        """
        self.project_root = Path(project_root)
        self.workspace_root = self.project_root / "workspace"

        if session_dir is not None:
            # Explicit directory override: use as-is and derive session_id from its name.
            self.session_dir = Path(session_dir)
            self.session_id = self.session_dir.name
        else:
            # Default behavior: workspace/{session_id}/
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

    # ------------------------------------------------------------------
    # FactSheet persistence (Phase 4 施策③)
    # ------------------------------------------------------------------

    def get_fact_sheet_path(self) -> Path:
        """Get path to FactSheet file (リサーチ事実抽出結果)."""
        return self.session_dir / "fact_sheet.json"

    def save_fact_sheet(self, fact_sheet: "FactSheet") -> Path:
        """Save FactSheet to file.

        Args:
            fact_sheet: FactSheet instance

        Returns:
            Path to saved file
        """
        path = self.get_fact_sheet_path()
        path.write_text(fact_sheet.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_fact_sheet(self) -> "FactSheet":
        """Load FactSheet from file.

        Returns:
            FactSheet instance

        Raises:
            FileNotFoundError: If fact_sheet.json does not exist
        """
        from core.models.fact_sheet import FactSheet

        path = self.get_fact_sheet_path()
        if not path.exists():
            raise FileNotFoundError(
                f"FactSheet not found: {path}\n"
                f"Please run FactExtractor (Phase 4) first."
            )
        return FactSheet.model_validate_json(path.read_text(encoding="utf-8"))

    def has_fact_sheet(self) -> bool:
        """Check if FactSheet exists in this session."""
        return self.get_fact_sheet_path().exists()

    # ------------------------------------------------------------------
    # FactCheckReport persistence (FactChecker 後処理エージェント)
    # ------------------------------------------------------------------

    def get_fact_check_report_path(self) -> Path:
        """Get path to FactCheckReport file (生成台本のハルシネーション検出結果)."""
        return self.session_dir / "factcheck_report.json"

    def save_fact_check_report(self, report: "FactCheckReport") -> Path:
        """Save FactCheckReport to file.

        Args:
            report: FactCheckReport instance

        Returns:
            Path to saved file
        """
        path = self.get_fact_check_report_path()
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_fact_check_report(self) -> "FactCheckReport":
        """Load FactCheckReport from file.

        Returns:
            FactCheckReport instance

        Raises:
            FileNotFoundError: If factcheck_report.json does not exist
        """
        from core.models.fact_check_report import FactCheckReport

        path = self.get_fact_check_report_path()
        if not path.exists():
            raise FileNotFoundError(
                f"FactCheckReport not found: {path}\n"
                f"FactChecker may have been disabled or skipped due to an error."
            )
        return FactCheckReport.model_validate_json(path.read_text(encoding="utf-8"))

    def has_fact_check_report(self) -> bool:
        """Check if FactCheckReport exists in this session."""
        return self.get_fact_check_report_path().exists()

    # ------------------------------------------------------------------
    # Phase 3A: 自動修正後の Script (script_fixed.json)
    # ------------------------------------------------------------------
    # FactFixAgent が high/medium issue を修正した後の Script を別ファイルとして
    # 保存する。元の script.json は手付かずで残し、音声合成は script_fixed.json
    # を優先（存在する場合のみ）。

    def get_script_fixed_path(self) -> Path:
        """Get path to auto-fixed Script file (FactFixAgent 出力)."""
        return self.session_dir / "script_fixed.json"

    def save_script_fixed(self, script) -> Path:
        """Save auto-fixed Script to script_fixed.json.

        Args:
            script: Script instance (core.models.script.Script)

        Returns:
            Path to saved file
        """
        path = self.get_script_fixed_path()
        path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
        return path

    def has_script_fixed(self) -> bool:
        """Check if script_fixed.json exists in this session."""
        return self.get_script_fixed_path().exists()

    def load_script_fixed(self):
        """Load auto-fixed Script from script_fixed.json.

        Returns:
            Script: 修正後の Script インスタンス

        Raises:
            FileNotFoundError: 未生成（FactFixAgent が無効 or エラー）の場合
        """
        from core.models.script import Script
        path = self.get_script_fixed_path()
        if not path.exists():
            raise FileNotFoundError(
                f"script_fixed.json not found: {path}\n"
                f"FactFixAgent may be disabled or no high/medium issues were detected."
            )
        return Script.model_validate_json(path.read_text(encoding="utf-8"))

    def get_session_status(self) -> dict:
        """Get current session status

        Returns:
            Dictionary with phase completion status
        """
        return {
            "session_id": self.session_id,
            "session_dir": str(self.session_dir),
            "research_completed": self.has_research_brief(),
            "fact_extraction_completed": self.has_fact_sheet(),
            "curation_completed": self.has_curation_result(),
            "show_plan_completed": self.has_show_plan(),
            "scripting_completed": self.has_script_artifact(),
        }
