"""FactSheet - Research 事実抽出エージェントのデータモデル（Phase 4 施策③）

FactExtractor エージェントが Perplexity のリサーチ生文字列から、構造化された
**事実（Fact）** のリストを抽出するために使用する。抽出された FactSheet は
TopicCurator に渡され、「どのトピックが面白いか」を数値・固有名詞ベースで
判断する材料となる。

後方互換性:
  - FactSheet は追加レイヤであり、既存の ResearchBrief / CurationResult 構造は保持される。
  - fact_extractor が無効な場合、TopicCurator は fact_sheet=None で従来通り動作する。

## カテゴリ定義の SSOT（Phase 4 review #8）

`FactCategory` に列挙する 9 値は `config/prompts.yaml` の `orchestrator.fact_extractor`
セクションで LLM に指示しているカテゴリ一覧と**双方向に連動**する:

  - **SSOT（ソース）**: `config/prompts.yaml` > `orchestrator.fact_extractor` の
    「## カテゴリの選び方」節
  - **消費側（型固定）**: 本モジュールの `FactCategory` リテラル型

両者を必ず同時に更新すること（一方のみ変えると LLM 出力が型検証で弾かれて
フォールバック "その他" に落ちる）。fact_extractor.py の `_parse_fact_sheet_response`
は未知値を警告ログ付きで "その他" に正規化するフォールバックを持つが、これは
防御層であり、正規の運用では SSOT 同期を保つのが前提。
"""
import logging
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FactCategory - Phase 4 review #8 で型固定
# ---------------------------------------------------------------------------
# SSOT: config/prompts.yaml > orchestrator.fact_extractor の「## カテゴリの選び方」
# 変更する場合は prompts.yaml と本定義の**両方**を同時に更新すること。
# fact_extractor.py 側では `_VALID_FACT_CATEGORIES` として集合化して参照する。
# 2026-05-02: 「イベント」「技術」「定義」を追加（旧 6 値→9 値）。
# qwen2.5-coder:32b 等の構造化出力モデルが技術解説コンテンツで自然に使う
# カテゴリが SSOT 外で WARNING を量産していたため、運用実態に合わせて拡張。
FactCategory = Literal[
    "数値", "人物", "事件", "比較", "引用",
    "イベント", "技術", "定義",
    "その他",
]


class ExtractedFact(BaseModel):
    """リサーチから抽出された1つの事実

    各フィールドは軽量モデルでも抽出しやすいよう粒度を小さく保つ。
    numeric_value / entity は該当するものがあれば埋め、なければ None でよい。

    category の許容値は `FactCategory` リテラルで型固定されている（Phase 4 review #8）。
    LLM が想定外の値を返した場合は `fact_extractor.py` のパース層で "その他" に
    フォールバックされる（warning ログ付き）。
    """
    statement: str = Field(
        ...,
        description="事実の1文（100〜200字目安、修飾語を避けて端的に）"
    )
    category: FactCategory = Field(
        default="その他",
        description=(
            "ファクトのカテゴリ。許容値: 数値／人物／事件／比較／引用／"
            "イベント／技術／定義／その他。"
            "SSOT は config/prompts.yaml > orchestrator.fact_extractor。"
        ),
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

    # ------------------------------------------------------------------
    # Phase 3 (interface_spec.md v1.0): リサーチ側で事前抽出された
    # `structured_facts` を FactSheet に変換するクラスメソッド。
    # ScriptOrchestrator が research_brief.structured_facts を検出した際に
    # FactExtractor をスキップして直接これを呼び出す。
    # ------------------------------------------------------------------

    @classmethod
    def from_structured_facts(cls, structured_facts: Dict[str, Any]) -> "FactSheet":
        """`research_brief.structured_facts` を FactSheet に変換する

        interface_spec.md 3.1 節の構造化ファクトを ExtractedFact のリストに
        マッピングする。リサーチ側が事前抽出したファクトをそのまま
        TopicCurator の判断材料に流用するための変換関数。

        変換マッピング:
          - key_numbers[*]      → ExtractedFact(category="数値", ...)
          - key_entities[*]     → ExtractedFact(category=type で分岐, ...)
          - surprising_claims[*]→ ExtractedFact(category="その他", surprise_score=9, ...)
          - controversies[*]    → ExtractedFact(category="比較", ...)

        Args:
            structured_facts: research_brief.structured_facts の dict（None 不可）

        Returns:
            FactSheet: 変換結果。サブフィールドが空 / 不正でも例外は投げず
                       スキップして可能な分だけ詰めた FactSheet を返す（防御的）。

        Notes:
            - source_idx は `[N]` 形式の文字列にして source_citation に格納する
              （後段 SegmentGenerator での引用追跡用）
            - 不正なエントリ（dict でない / 必須キー欠損）は logger.warning で
              記録してスキップ
            - extractor_reasoning には変換元を識別する固定文言を入れる
              （HITL/debug 時に「これは LLM 抽出ではなく structured_facts 由来」と判別可能）
        """
        facts: List[ExtractedFact] = []

        if not isinstance(structured_facts, dict):
            logger.warning(
                "FactSheet.from_structured_facts: expected dict, got %s; "
                "returning empty FactSheet",
                type(structured_facts).__name__,
            )
            return cls(
                facts=[],
                theme_summary="",
                extractor_reasoning=(
                    "Generated from research_brief.structured_facts "
                    "(input was not a dict; returned empty FactSheet)"
                ),
            )

        # ----- key_numbers → カテゴリ "数値" -----
        for item in structured_facts.get("key_numbers", []) or []:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict key_numbers entry: %r", item)
                continue
            value = str(item.get("value", "") or "").strip()
            unit = str(item.get("unit", "") or "").strip()
            context = str(item.get("context", "") or "").strip()
            if not context:
                # statement が無いと ExtractedFact が成立しない
                logger.warning("Skipping key_numbers entry without context: %r", item)
                continue
            numeric_value = (value + unit).strip() or None
            try:
                facts.append(ExtractedFact(
                    statement=context,
                    category="数値",
                    numeric_value=numeric_value,
                    entity=None,
                    source_citation=_format_source_citation(item.get("source_idx")),
                    surprise_score=7,
                ))
            except Exception as e:
                logger.warning("Failed to build ExtractedFact from key_numbers %r: %s", item, e)

        # ----- key_entities → カテゴリは type で分岐 -----
        for item in structured_facts.get("key_entities", []) or []:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict key_entities entry: %r", item)
                continue
            name = str(item.get("name", "") or "").strip()
            entity_type = str(item.get("type", "") or "").strip().lower()
            role = str(item.get("role", "") or "").strip()
            # statement: name と role を組み合わせた1文を生成
            if not name and not role:
                logger.warning("Skipping key_entities entry without name/role: %r", item)
                continue
            statement = f"{name}: {role}" if name and role else (name or role)
            try:
                facts.append(ExtractedFact(
                    statement=statement,
                    category=_entity_type_to_category(entity_type),
                    numeric_value=None,
                    entity=name or None,
                    source_citation=_format_source_citation(item.get("source_idx")),
                    surprise_score=5,
                ))
            except Exception as e:
                logger.warning("Failed to build ExtractedFact from key_entities %r: %s", item, e)

        # ----- surprising_claims → カテゴリ "その他"、surprise_score 高め -----
        for item in structured_facts.get("surprising_claims", []) or []:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict surprising_claims entry: %r", item)
                continue
            statement = str(item.get("statement", "") or "").strip()
            if not statement:
                logger.warning("Skipping surprising_claims entry without statement: %r", item)
                continue
            why = str(item.get("why_surprising", "") or "").strip()
            # why_surprising があれば statement 末尾に付与（理由をファクト本文に保持）
            full_statement = f"{statement}（驚き: {why}）" if why else statement
            try:
                facts.append(ExtractedFact(
                    statement=full_statement,
                    category="その他",
                    numeric_value=None,
                    entity=None,
                    source_citation=_format_source_citation(item.get("source_idx")),
                    surprise_score=9,
                ))
            except Exception as e:
                logger.warning("Failed to build ExtractedFact from surprising_claims %r: %s", item, e)

        # ----- controversies → カテゴリ "比較" -----
        for item in structured_facts.get("controversies", []) or []:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict controversies entry: %r", item)
                continue
            position_a = str(item.get("position_a", "") or "").strip()
            position_b = str(item.get("position_b", "") or "").strip()
            if not position_a or not position_b:
                logger.warning("Skipping controversies entry without both positions: %r", item)
                continue
            statement = f"{position_a} vs {position_b}"
            # source_indices (list) を [N,M] 形式で連結
            source_indices = item.get("source_indices") or []
            citation: Optional[str] = None
            if isinstance(source_indices, list) and source_indices:
                citation = "[" + ",".join(str(idx) for idx in source_indices) + "]"
            try:
                facts.append(ExtractedFact(
                    statement=statement,
                    category="比較",
                    numeric_value=None,
                    entity=None,
                    source_citation=citation,
                    surprise_score=7,
                ))
            except Exception as e:
                logger.warning("Failed to build ExtractedFact from controversies %r: %s", item, e)

        # surprise_score 降順に並べる（既存 FactSheet と同じ順序契約）
        facts.sort(key=lambda f: f.surprise_score, reverse=True)

        return cls(
            facts=facts,
            theme_summary="",
            extractor_reasoning=(
                f"Generated from research_brief.structured_facts "
                f"(リサーチ側で事前抽出済み、{len(facts)} 件を変換)"
            ),
        )


# ---------------------------------------------------------------------------
# from_structured_facts 用の内部ヘルパー（モジュールレベル、テストしやすさ重視）
# ---------------------------------------------------------------------------

# key_entities.type → FactCategory のマッピング。
# interface_spec.md 3.1 例の "institution" 等の代表値をカバーし、未知 type は
# "その他" にフォールバック。明示マッピングを増やしたいときはここを更新する。
_ENTITY_TYPE_TO_CATEGORY: Dict[str, "FactCategory"] = {
    "person": "人物",
    "people": "人物",
    "researcher": "人物",
    "scientist": "人物",
    "author": "人物",
    "institution": "定義",
    "organization": "定義",
    "company": "定義",
    "university": "定義",
    "agency": "定義",
    "tech": "技術",
    "technology": "技術",
    "product": "技術",
    "system": "技術",
    "algorithm": "技術",
    "concept": "定義",
    "term": "定義",
    "event": "イベント",
    "conference": "イベント",
    "release": "イベント",
}


def _entity_type_to_category(entity_type: str) -> "FactCategory":
    """key_entities.type を FactCategory に正規化。未知 type は "その他" に落とす。"""
    if not entity_type:
        return "その他"
    return _ENTITY_TYPE_TO_CATEGORY.get(entity_type.lower(), "その他")


def _format_source_citation(source_idx: Any) -> Optional[str]:
    """source_idx を `[N]` 形式の citation 文字列に変換。None / 空は None を返す。"""
    if source_idx is None:
        return None
    s = str(source_idx).strip()
    if not s:
        return None
    return f"[{s}]"
