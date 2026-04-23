"""FactSheet - Research 事実抽出エージェントのデータモデル（Phase 4 施策③）

FactExtractor エージェントが Perplexity のリサーチ生文字列から、構造化された
**事実（Fact）** のリストを抽出するために使用する。抽出された FactSheet は
TopicCurator に渡され、「どのトピックが面白いか」を数値・固有名詞ベースで
判断する材料となる。

後方互換性:
  - FactSheet は追加レイヤであり、既存の ResearchBrief / CurationResult 構造は保持される。
  - fact_extractor が無効な場合、TopicCurator は fact_sheet=None で従来通り動作する。
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class ExtractedFact(BaseModel):
    """リサーチから抽出された1つの事実

    各フィールドは軽量モデルでも抽出しやすいよう粒度を小さく保つ。
    numeric_value / entity は該当するものがあれば埋め、なければ None でよい。
    """
    statement: str = Field(
        ...,
        description="事実の1文（100〜200字目安、修飾語を避けて端的に）"
    )
    category: str = Field(
        default="general",
        description="ファクトのカテゴリ（数値／人物／事件／比較／引用／その他）"
    )
    numeric_value: Optional[str] = Field(
        default=None,
        description="この事実に含まれる数値表現（例: '1200万円', '3.4倍', '2023年'）"
    )
    entity: Optional[str] = Field(
        default=None,
        description="主語となる固有名詞（例: 'OpenAI', '日銀', '山田太郎'）"
    )
    source_citation: Optional[str] = Field(
        default=None,
        description="リサーチ本文中の出典や手がかり（例: 元URLの識別子、章題など）"
    )
    surprise_score: int = Field(
        default=5,
        ge=1,
        le=10,
        description="意外性スコア（1=誰もが知っている, 10=専門家も驚く）"
    )


class FactSheet(BaseModel):
    """Research 事実抽出エージェントの出力

    TopicCurator が意思決定に使うための構造化された素材。
    facts はリサーチ量に応じて可変（20-40件目安）、surprise_score の降順で
    抽出されることが望ましい（Curator 側のソートにも依存しない前処理）。
    """
    facts: List[ExtractedFact] = Field(
        default_factory=list,
        description="抽出された事実のリスト（surprise_score 降順推奨）"
    )
    theme_summary: str = Field(
        default="",
        description="研究テーマの1段落要約（200〜400字、Curator 判断の土台）"
    )
    extractor_reasoning: str = Field(
        default="",
        description="FactExtractor がこの抽出結果にした理由（デバッグ・HITL 参照用、改行なし）"
    )

    # ------------------------------------------------------------------
    # Convenience accessors for Curator prompt injection
    # ------------------------------------------------------------------

    def top_facts(self, limit: int = 10) -> List[ExtractedFact]:
        """surprise_score の降順で上位 limit 件を返す"""
        return sorted(self.facts, key=lambda f: f.surprise_score, reverse=True)[:limit]

    def is_empty(self) -> bool:
        """抽出に失敗した・空の FactSheet かどうか"""
        return not self.facts and not self.theme_summary.strip()
