"""リサーチ関連のデータモデル

AIプロデューサー機能で使用する検索計画モデルと、リサーチ結果モデルを定義
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class ResearchSource(BaseModel):
    """リサーチソース（参照元）を表すモデル"""
    title: str = Field(..., description="ソースのタイトル")
    url: str = Field(..., description="ソースのURL")
    snippet: Optional[str] = Field(None, description="引用スニペット（オプション）")
    published_date: Optional[str] = Field(
        None,
        description="公開日 (VerifiedScript.references.published_date 由来、概要欄の参考文献表記用)",
    )


class ResearchResult(BaseModel):
    """リサーチ結果を格納するモデル"""
    query: str = Field(..., description="検索クエリ")
    raw_content: str = Field(..., description="LLM/検索エンジンからの生の回答テキスト")
    sources: List[ResearchSource] = Field(default_factory=list, description="参照元のリスト")
    
    # 処理メタデータ
    timestamp: Optional[str] = Field(None, description="リサーチ実行時刻")
    provider: str = Field(default="perplexity", description="リサーチプロバイダー")
    
    # 後方互換性のため、既存のフィールドも保持
    mode: Optional[str] = Field(None, description="リサーチモード（後方互換性）")
    content: Optional[str] = Field(None, description="リサーチ内容（後方互換性）")
    
    def __init__(self, **data):
        """初期化時に後方互換性を処理"""
        # contentが指定されている場合、raw_contentにコピー
        if 'content' in data and 'raw_content' not in data:
            data['raw_content'] = data['content']
        # queryが指定されていない場合、デフォルト値を設定
        if 'query' not in data:
            data['query'] = data.get('mode', 'unknown')
        super().__init__(**data)


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
