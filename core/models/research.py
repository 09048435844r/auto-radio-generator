"""リサーチ関連のデータモデル

AIプロデューサー機能で使用する検索計画モデルを定義
"""
from pydantic import BaseModel, Field


class ResearchPlan(BaseModel):
    """検索計画モデル
    
    AIプロデューサーが考案した、多角的な検索クエリと台本の切り口
    """
    queries: list[str] = Field(
        ...,
        description="Perplexityに投げる検索クエリのリスト（通常3つ）",
        min_length=1,
        max_length=5
    )
    angle: str = Field(
        ...,
        description="今回の台本の切り口・コンセプト"
    )
    
    def get_queries_summary(self) -> str:
        """クエリのサマリーを取得"""
        return "\n".join([f"{i+1}. {q}" for i, q in enumerate(self.queries)])
