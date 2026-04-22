"""ShowPlan - 番組構成プランナーのデータモデル（Phase 3 施策④）

ShowRunner エージェントが Curator 後に番組全体の構成（アーク・ブリッジ・トーン）
を設計するために使用する。SegmentGenerator は各セグメント生成時に ShowPlan
の該当部分を参照し、ダイジェスト感ではなく番組全体の一貫したストーリーとして
生成することを目指す。

後方互換性: ShowPlan が存在しないセッションでは Orchestrator/SegmentGenerator
は ShowPlan=None として動作し、従来通りの出力となる。
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class TopicBridge(BaseModel):
    """トピック間のブリッジ（接続台詞）設計

    from_topic_index / to_topic_index は CurationResult.topics の 0-based インデックス。
    intro→topic[0] のブリッジは from=-1 で表現する（導入から1本目の深掘りへの橋）。
    最後のトピック→conclusion のブリッジは to=-1 で表現する（最終深掘りからまとめへの橋）。
    """
    from_topic_index: int = Field(
        ...,
        description="接続元のトピックインデックス（0始まり、-1 は導入セグメント）"
    )
    to_topic_index: int = Field(
        ...,
        description="接続先のトピックインデックス（0始まり、-1 はまとめセグメント）"
    )
    transition_hint: str = Field(
        ...,
        description="このブリッジの意図・演出ヒント（例: '対比を強調', '驚きから納得へ反転'）"
    )


class ShowPlan(BaseModel):
    """番組全体の構成プラン - ShowRunnerエージェントの出力

    番組を単なるトピック列挙（ダイジェスト）ではなく、一貫したアーク（起伏）を
    持つ「番組」として設計するためのメタ情報。
    """
    overall_arc: str = Field(
        ...,
        description="番組全体のストーリーアーク（例: '謎提示→驚愕の事実→反転→余韻'、80〜150文字）"
    )
    intro_hook_strategy: str = Field(
        ...,
        description="導入部で使うフックの方針（例: '冒頭3ターンで最大の数字を提示して視聴者の時間投資を正当化'）"
    )
    topic_bridges: List[TopicBridge] = Field(
        default_factory=list,
        description="トピック間のブリッジ設計。intro→topic[0]、topic[i]→topic[i+1]、topic[last]→conclusionの順"
    )
    conclusion_strategy: str = Field(
        ...,
        description="締めの設計（例: '視聴者に持ち帰ってほしい一言を1つに絞り、余韻を残す質問で終わる'）"
    )
    overall_tone: str = Field(
        ...,
        description="番組全体のトーン配分（例: '驚き多め、ユーモア控えめ、最後だけ余韻重視'）"
    )
    planner_reasoning: str = Field(
        default="",
        description="ShowRunnerがこの構成にした理由（デバッグ・HITL参照用、200文字程度）"
    )

    # ------------------------------------------------------------------
    # Convenience accessors for SegmentGenerator
    # ------------------------------------------------------------------

    def get_bridge_into(self, topic_index: int) -> Optional[TopicBridge]:
        """あるトピックに"入る"ブリッジ（そのトピックが to_topic_index のもの）を返す

        Args:
            topic_index: 対象トピックインデックス（0始まり、-1はconclusion）

        Returns:
            該当するTopicBridge、なければNone
        """
        for bridge in self.topic_bridges or []:
            if bridge.to_topic_index == topic_index:
                return bridge
        return None

    def get_bridge_out_of(self, topic_index: int) -> Optional[TopicBridge]:
        """あるトピックから"出る"ブリッジ（そのトピックが from_topic_index のもの）を返す

        Args:
            topic_index: 対象トピックインデックス（0始まり、-1はintro）

        Returns:
            該当するTopicBridge、なければNone
        """
        for bridge in self.topic_bridges or []:
            if bridge.from_topic_index == topic_index:
                return bridge
        return None
