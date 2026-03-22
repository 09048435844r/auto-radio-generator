"""台本オーケストレーターインターフェース"""
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from core.models import Script, AppConfig
from core.models.curation import CurationResult

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult


class IScriptOrchestrator(ABC):
    """台本オーケストレーターの抽象インターフェース

    Hierarchical Agentic Workflow による段階的台本生成を担う。
    - Step 1: TopicCurator によるトピック選定
    - Step 2: SegmentGenerator による順次セグメント生成
    - Step 3: ScriptOrchestrator による統合
    """

    def __init__(self, config: AppConfig):
        self.config = config

    @abstractmethod
    async def generate_script(
        self,
        theme: str,
        research_data: "ResearchResult",
        avoid_topics: Optional[str] = None,
        excluded_topics: Optional[str] = None,
        progress_callback=None,
    ) -> Script:
        """テーマとリサーチデータから長尺台本を生成する

        Args:
            theme: 動画のテーマ
            research_data: リサーチ結果
            avoid_topics: 避けてほしい話題（Negative Prompt）
            excluded_topics: 第2部モード用、第1部コンテキスト
            progress_callback: 進捗報告コールバック (log関数)

        Returns:
            Script: 統合された台本オブジェクト
        """
        pass

    @abstractmethod
    async def curate_topics(
        self,
        research_data: "ResearchResult",
        target_count: int = 3,
    ) -> CurationResult:
        """リサーチデータから面白いトピックを選定する

        Args:
            research_data: リサーチ結果
            target_count: 選定するトピック数

        Returns:
            CurationResult: 選定されたトピックと選定理由
        """
        pass
