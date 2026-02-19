"""リサーチャーインターフェース（ABC）"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, TYPE_CHECKING

from core.models import AppConfig
from core.models.research import ResearchSource

if TYPE_CHECKING:
    from core.models.usage import PerplexityUsage


ResearchMode = Literal["debate", "voices", "trivia", "weekly_digest", "lecture"]


@dataclass
class ResearchResult:
    """リサーチ結果"""
    topic: str
    mode: ResearchMode
    content: str
    sources: list[ResearchSource] | None = None
    usage: "PerplexityUsage | None" = None


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
