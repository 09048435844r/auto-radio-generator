"""キュレーションと台本セグメントのデータモデル"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class CuratedTopic(BaseModel):
    """キュレーション済みトピック - リサーチデータから選定された面白いネタ"""
    title: str = Field(..., description="トピックタイトル（例: 'CGMの精度問題と血糖値測定の誤差'）")
    content: str = Field(..., description="詳細情報（500〜800文字、具体例・数値データ含む）")
    priority: int = Field(..., description="優先度（1が最高）")
    estimated_turns: int = Field(default=30, description="推定ターン数（20〜40）")
    tone: str = Field(default="議論", description="推奨トーン（例: '驚き', '議論', '解説'）")
    key_facts: List[str] = Field(
        default_factory=list,
        description="最重要ファクトのリスト（数値・固有名詞・エピソード）"
    )
    selection_reason: str = Field(
        default="",
        description="このトピックを選んだ理由（80〜120字、面白さの核心。下流のSegmentGeneratorに渡される）"
    )


class ScriptSegment(BaseModel):
    """台本の1セグメント - 独立したAPI呼び出しで生成された会話ブロック"""
    segment_id: str = Field(..., description="セグメントID（例: 'intro', 'deep_dive_1', 'conclusion'）")
    segment_type: Literal["intro", "deep_dive", "conclusion"] = Field(
        ..., description="セグメント種別"
    )
    topic_title: Optional[str] = Field(
        None, description="深掘りセグメントの場合のトピックタイトル"
    )
    turns: List[dict] = Field(
        ..., description="このセグメントの対話ターン（DialogueTurn互換）"
    )
    context_summary: str = Field(
        default="",
        description="このセグメントまでの文脈要約（次セグメント生成用、200〜300文字）"
    )
    token_count: int = Field(default=0, description="このセグメントの出力トークン数")


class CurationResult(BaseModel):
    """キュレーション結果 - TopicCuratorの出力"""
    topics: List[CuratedTopic] = Field(..., description="選定されたトピック（優先度順）")
    curator_reasoning: str = Field(
        default="",
        description="選定理由（デバッグ用）"
    )
