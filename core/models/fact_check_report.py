"""FactCheckReport - ファクトチェックエージェントのデータモデル

FactCheckAgent が生成台本（Script）とリサーチデータ（ResearchBrief）を
LLM に投げ込み、ハルシネーション・誇張・出典不明な主張を検出した結果を
構造化して保持する。

設計方針:
  - FactExtractor / FactSheet と同じ Pydantic + Literal パターン
  - severity は high/medium/low の 3 値で固定（SSOT は本モジュール）
  - overall_confidence は 0-100 の整数（UI 側で色分け表示）
  - 出力先: <session>/factcheck_report.json（SessionManager 経由で永続化）

Phase 3A 追記: FactFixAgent が high/medium issue を自動修正した結果は
  fixed_text / auto_fixed フィールドに格納する（low はスキップ）。
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# severity の許容値 SSOT。プロンプト（config/prompts.yaml > orchestrator.fact_checker）
# と双方向に連動する。値を増やす場合は両方を同時に更新すること。
FactCheckSeverity = Literal["high", "medium", "low"]


class FactCheckIssue(BaseModel):
    """ファクトチェックで検出された 1 件の問題

    台本中の問題箇所（script_quote）と、何が問題か（issue）、
    どう直すべきか（suggestion）を組で持つ。LLM が抽出する。
    """
    severity: FactCheckSeverity = Field(
        ...,
        description=(
            "問題の深刻度: high=明確な誤り/誇張, medium=出典不明や曖昧な主張, "
            "low=軽微な脚色・補足推奨。SSOT は core.models.fact_check_report.FactCheckSeverity。"
        ),
    )
    script_quote: str = Field(
        ...,
        description="問題のある台本の一節（30〜200 文字目安、原文ママで引用）",
    )
    issue: str = Field(
        ...,
        description="何が問題か（事実の誤り / 出典なし / 過度な一般化 等を具体的に説明）",
    )
    suggestion: str = Field(
        ...,
        description="修正案（書き換え案 or 追加すべき出典 or 削除推奨等の具体的な推奨）",
    )
    # Phase 3A: 自動修正エンジンによる修正結果
    fixed_text: Optional[str] = Field(
        default=None,
        description=(
            "FactFixAgent が生成した修正後テキスト（script_quote の置換候補）。"
            "auto_fixed=True の場合のみ非 None。low severity は対象外。"
        ),
    )
    auto_fixed: bool = Field(
        default=False,
        description=(
            "FactFixAgent による自動修正が成功したか。True なら fixed_text が"
            "セットされ、UI で『修正前/修正後』表示に切り替わる。"
        ),
    )


class FactCheckReport(BaseModel):
    """ファクトチェックエージェントの最終出力

    overall_confidence は 0-100 の整数で、台本全体の信頼度を表す。
    Gradio UI 側で色分け表示される（80以上=緑、60-79=黄、59以下=赤）。
    issues は severity 降順で並べる前提（high → medium → low）。
    """
    overall_confidence: int = Field(
        ...,
        ge=0,
        le=100,
        description="台本全体の信頼度スコア (0-100)。100=完全に裏付けあり、0=ハルシネーション多発。",
    )
    issues: List[FactCheckIssue] = Field(
        default_factory=list,
        description="検出された問題のリスト（severity high → medium → low の順を推奨）",
    )
    summary: str = Field(
        default="",
        description="ファクトチェック全体の所見（150〜300 字目安、UI のヘッダー表示用）",
    )

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def issues_by_severity(self, severity: FactCheckSeverity) -> List[FactCheckIssue]:
        """指定 severity の issues のみを返す（UI のフィルタ用）"""
        return [i for i in self.issues if i.severity == severity]

    def has_critical_issues(self) -> bool:
        """high severity の issue が 1 件でもあれば True"""
        return any(i.severity == "high" for i in self.issues)

    def confidence_band(self) -> Literal["green", "yellow", "red"]:
        """overall_confidence を UI 表示用の 3 段階バンドに正規化する"""
        if self.overall_confidence >= 80:
            return "green"
        if self.overall_confidence >= 60:
            return "yellow"
        return "red"
