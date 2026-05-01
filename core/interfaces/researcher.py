"""リサーチャーインターフェース（ABC）"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, TYPE_CHECKING

from core.models import AppConfig
from core.models.research import ResearchSource

if TYPE_CHECKING:
    from core.models.usage import PerplexityUsage


ResearchMode = Literal["debate", "voices", "trivia", "weekly_digest", "lecture"]


@dataclass
class ResearchResult:
    """リサーチ結果

    Phase 3 (interface_spec.md v1.0) で `structured_facts` を追加。
    研究側パイプラインが事前抽出した構造化ファクトを台本側 ScriptOrchestrator まで
    伝播させるための搬送経路。後方互換: None 既定なので既存呼び出し元は影響なし。
    """
    topic: str
    mode: ResearchMode
    content: str
    sources: list[ResearchSource] | None = None
    usage: "PerplexityUsage | None" = None
    # Phase 3: research_brief.structured_facts を scripting_phase の変換点で
    # ここに乗せ、ScriptOrchestrator Step 0.5 で FactExtractor をスキップする
    # トリガとして利用する。形式は interface_spec.md 3.1 節準拠（dict）。
    structured_facts: Optional[Dict[str, Any]] = None


class IResearcher(ABC):
    """リサーチャーの抽象基底クラス
    
    テーマに関する情報を収集し、台本生成の素材を提供する。
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
    
    @abstractmethod
    async def research(self, topic: str, mode: ResearchMode) -> ResearchResult:
        """テーマについてリサーチを実行する
        
        Args:
            topic: リサーチするテーマ
            mode: リサーチモード（debate/voices/trivia）
        
        Returns:
            ResearchResult: リサーチ結果
        """
        pass
    
    @abstractmethod
    async def check_api_status(self) -> bool:
        """APIの接続状態を確認する
        
        Returns:
            bool: 接続可能ならTrue
        """
        pass
