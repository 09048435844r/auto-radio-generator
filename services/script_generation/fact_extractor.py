"""FactExtractor - Research 事実抽出エージェント（Phase 4 施策③）

Hierarchical Agentic Workflow の Step 0.5（Curator の前段）。
Perplexity のリサーチ生文字列から構造化された FactSheet を抽出し、
TopicCurator が「どのトピックが面白いか」を数値・固有名詞ベースで判断する
材料を供給する。

TopicCurator / ShowRunner と同型のアーキテクチャ:
  - ILLMPort 経由で provider-agnostic
  - PromptManager から system_prompt を取得
  - JSON レスポンスをサニタイズ付きでパース
  - last_usage でトークン使用量を公開
  - last_fact_sheet でパイプライン層からの永続化を可能にする

後方互換性:
  - fact_extractor.enabled=False ならこのエージェントは一切呼ばれず、
    TopicCurator は fact_sheet=None で従来通り動作する。
"""
import json
import logging
from typing import Optional, TYPE_CHECKING, get_args as _typing_get_args

from rich.console import Console

from core.models import AppConfig, LLMUsage
from core.models.fact_sheet import ExtractedFact, FactCategory, FactSheet
from core.utils import sanitize_json_response
from core.prompt_manager import PromptManager
from core.interfaces.llm_port import ILLMPort, LLMRequest

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult

logger = logging.getLogger(__name__)
console = Console()

# Phase 4 review #8: SSOT (config/prompts.yaml > orchestrator.fact_extractor) と連動。
# FactCategory リテラル型から runtime 集合を派生させ、LLM 出力検証に使う。
# typing.get_args を経由することで FactCategory の値を一点管理にできる（SSOT 同期の代償ゼロ）。
_VALID_FACT_CATEGORIES: frozenset[str] = frozenset(_typing_get_args(FactCategory))
_DEFAULT_FACT_CATEGORY: FactCategory = "その他"


class FactExtractor:
    """Research 事実抽出エージェント

    TopicCurator と同じ軽量モデルで動作する想定。
    1回の LLM 呼び出しで FactSheet を生成する。
    """

    def __init__(self, llm_port: ILLMPort, config: AppConfig):
        """Initialize FactExtractor with LLM port

        Args:
            llm_port: LLM port interface for provider-agnostic communication
            config: Application configuration
        """
        self._llm = llm_port
        self.config = config
        self.prompt_manager = PromptManager()

        orch_cfg = config.yaml.script_generator.orchestrator
        # FactExtractor config (backward compatible: falls back to curator_model if not set)
        fe_cfg = getattr(orch_cfg, "fact_extractor", None)
        self.fact_extractor_model = (getattr(fe_cfg, "model", "") or "").strip() or orch_cfg.curator_model
        self.max_facts = int(getattr(fe_cfg, "max_facts", 30) or 30)
        # Phase 4 review #7: max_tokens is now config-driven so production can scale it
        # independently of max_facts without a code change.
        self.max_tokens = int(getattr(fe_cfg, "max_tokens", 8192) or 8192)

        self.last_usage: Optional[LLMUsage] = None
        # Expose the last successfully-produced FactSheet so the pipeline layer
        # can persist it without re-invoking the agent.
        self.last_fact_sheet: Optional[FactSheet] = None

    async def extract_facts(
        self,
        theme: str,
        research_data: "ResearchResult",
        progress_log=None,
    ) -> FactSheet:
        """リサーチ生文字列から FactSheet を抽出する

        Args:
            theme: 番組のテーマ
            research_data: Perplexity から取得したリサーチ結果
            progress_log: 進捗ログ関数（オプション）

        Returns:
            FactSheet: 抽出された事実シート

        Raises:
            ValueError: research_data.content が空の場合（抽出不能）
            Exception: LLM 呼び出し or JSON パース失敗時
        """
        log = progress_log or (lambda msg: console.print(msg))

        content = (getattr(research_data, "content", "") or "").strip()
        if not content:
            raise ValueError("FactExtractor.extract_facts: research_data has no content to extract from")

        log(
            f"[cyan]📋 ファクト抽出開始 "
            f"(プロバイダー: {self._llm.provider_name}, モデル: {self.fact_extractor_model})[/cyan]"
        )
        log(f"  リサーチデータ: {len(content)}文字 → 最大 {self.max_facts} ファクトを抽出")

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "fact_extractor")
        user_prompt = self._build_fact_extractor_user_prompt(theme, research_data)

        try:
            response_text, usage = await self._call_api(system_prompt, user_prompt)
            self.last_usage = usage
            result = self._parse_fact_sheet_response(response_text)

            log(f"[green]✓ ファクト抽出完了: {len(result.facts)}件[/green]")
            if result.facts:
                top = result.top_facts(limit=3)
                for i, fact in enumerate(top, 1):
                    log(f"  {i}. [score={fact.surprise_score}] {fact.statement[:60]}...")
            self.last_fact_sheet = result
            return result

        except Exception as e:
            log(f"[red]✗ ファクト抽出エラー: {e}[/red]")
            logger.error(f"FactExtractor.extract_facts failed: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Internal: prompt building
    # ------------------------------------------------------------------

    def _build_fact_extractor_user_prompt(
        self,
        theme: str,
        research_data: "ResearchResult",
    ) -> str:
        """FactExtractor 用ユーザープロンプトを構築"""
        content = getattr(research_data, "content", "") or ""
        mode = getattr(research_data, "mode", "") or ""

        prompt = f"## テーマ\n{theme}\n\n"
        if mode:
            prompt += f"## リサーチモード\n{mode}\n\n"
        prompt += f"## 抽出目標\n最大 {self.max_facts} 件のファクトを抽出してください。\n\n"
        prompt += f"## リサーチ生文字列（全文）\n{content}\n\n"

        prompt += (
            "## 指示\n"
            "上記のリサーチ生文字列から、TopicCurator が判断材料として使える**構造化ファクト**を抽出してください。\n"
            "- 数値／固有名詞／事件／比較／引用を優先\n"
            "- **最低 5 件は抽出**（空配列は基本的に避ける。意外性スコア 4〜6 の"
            "『一般人にとって新情報』レベルも積極的に含める）\n"
            "- 1ファクト=1文（複数の事実を繋げない）\n"
            "- surprise_score の降順で並べる\n\n"
            "## 出力形式（JSON）\n"
            "**重要**: 以下の形式で有効なJSONのみを出力してください。\n"
            "- コードブロック（```json）は使用しないこと\n"
            "- 文字列内の改行は使用せず、すべて1行で記述すること\n\n"
            "## 例（リサーチテーマが『亜麻仁油の健康効果』の場合の出力イメージ）\n"
            "{\n"
            '  "facts": [\n'
            '    {\n'
            '      "statement": "デンマークの研究で亜麻仁油摂取者の70%が関節リウマチ症状を軽減した",\n'
            '      "category": "数値",\n'
            '      "numeric_value": "70%",\n'
            '      "entity": "デンマーク",\n'
            '      "source_citation": "本文中の出典や手がかり（なければ null）",\n'
            '      "surprise_score": 8\n'
            '    },\n'
            '    {\n'
            '      "statement": "英国の8週間臨床試験で亜麻仁油が65%のうつ症状を改善した",\n'
            '      "category": "数値",\n'
            '      "numeric_value": "65%",\n'
            '      "entity": "英国",\n'
            '      "source_citation": null,\n'
            '      "surprise_score": 7\n'
            '    }\n'
            '  ],\n'
            '  "theme_summary": "研究テーマの1段落要約（200〜400字、Curator 判断の土台となる）",\n'
            '  "extractor_reasoning": "どの観点で何件選んだかを80〜150文字で必ず記入（空文字禁止）"\n'
            "}\n"
            "\n"
            "**注意**: 上記例は「形式の参考」であり、実際の出力はユーザープロンプトの"
            "リサーチ内容に即したファクトを抽出すること。テーマが異なっていても"
            "「数値+固有名詞を含む具体的な1文」「最低5件」「surprise_score 降順」の"
            "原則は共通。\n"
        )
        return prompt

    # ------------------------------------------------------------------
    # Internal: API call (same pattern as TopicCurator / ShowRunner)
    # ------------------------------------------------------------------

    async def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, LLMUsage]:
        """Call LLM API for fact extraction"""
        # Defensive: if configured model looks Ollama-specific but provider isn't Ollama, fall back
        model_to_use = self.fact_extractor_model
        if model_to_use and self._llm.provider_name != "ollama":
            if ":" in model_to_use or model_to_use.startswith("ollama/"):
                logger.warning(
                    f"fact_extractor.model '{model_to_use}' appears to be Ollama-specific "
                    f"but provider is '{self._llm.provider_name}'. Using provider default."
                )
                model_to_use = None

        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model_to_use,
            max_tokens=self.max_tokens,  # Phase 4 review #7: config-driven
            temperature=0.2,   # 事実抽出は最低温度で安定性を確保
            response_format="json",
        )

        response = await self._llm.generate(request)

        # Phase 4 review #7: fail-fast on truncation.
        # Partial/broken JSON from length truncation was previously parsed optimistically,
        # which produced silently-corrupted FactSheets (missing tail facts, unterminated
        # strings re-accepted post-sanitize). The orchestrator has a fail-open around us
        # and will proceed with fact_sheet=None, so raising here keeps the contract that
        # a successful return means a syntactically complete LLM response.
        if response.finish_reason == "length":
            raise RuntimeError(
                "FactExtractor output was truncated (finish_reason=length). "
                f"Current max_tokens={self.max_tokens}. "
                "Increase fact_extractor.max_tokens in config.yaml or lower max_facts. "
                "Aborting rather than returning a partial FactSheet."
            )

        logger.debug(
            f"FactExtractor API: provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        return response.content, response.usage

    # ------------------------------------------------------------------
    # Internal: response parsing (same pattern as ShowRunner)
    # ------------------------------------------------------------------

    def _parse_fact_sheet_response(self, response_text: str) -> FactSheet:
        """API レスポンスを FactSheet に変換。失敗時は sanitize を試行。"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError as e:
            logger.error(f"[FactExtractor] JSON parse error: {e}")
            logger.error(
                f"[FactExtractor] Full raw response text ({len(response_text)} chars):\n"
                f"{'=' * 80}\n{response_text}\n{'=' * 80}"
            )
            console.print("[yellow]⚠️ FactExtractor JSONパースエラー。サニタイズ処理を試行中...[/yellow]")
            cleaned = sanitize_json_response(response_text, "FactExtractor")
            try:
                data = json.loads(cleaned, strict=False)
                console.print("[green]✓ サニタイズ後のパースに成功[/green]")
            except json.JSONDecodeError as e2:
                logger.error(f"[FactExtractor] JSON parse failed after sanitization: {e2}")
                console.print("[red]✗ FactExtractor: サニタイズ後もJSONパース失敗[/red]")
                raise

        # Parse facts defensively: skip malformed entries, never crash the whole extraction
        facts: list[ExtractedFact] = []
        for f in data.get("facts", []) or []:
            try:
                statement = str(f.get("statement", "") or "").strip()
                if not statement:
                    # Skip empty facts silently (LLMs sometimes emit placeholders)
                    continue

                # Clamp surprise_score to 1-10 range defensively
                raw_score = f.get("surprise_score", 5)
                try:
                    score = int(raw_score)
                except (TypeError, ValueError):
                    score = 5
                score = max(1, min(10, score))

                # numeric_value / entity / source_citation: normalize "null"/"" to None
                def _norm_optional(val) -> Optional[str]:
                    if val is None:
                        return None
                    s = str(val).strip()
                    if not s or s.lower() == "null":
                        return None
                    return s

                # Phase 4 review #8: category を FactCategory リテラルに正規化する。
                # LLM が SSOT（prompts.yaml の 6 カテゴリ）以外を返した場合、
                # ValidationError を避けるため _DEFAULT_FACT_CATEGORY にフォールバック。
                # 未知値の出現頻度は logger.warning で追跡可能（BACKLOG の将来分布調査用）。
                raw_category = str(f.get("category", "") or "").strip()
                if raw_category in _VALID_FACT_CATEGORIES:
                    category: FactCategory = raw_category  # type: ignore[assignment]
                else:
                    if raw_category:
                        logger.warning(
                            f"[FactExtractor] Unknown category '{raw_category}' "
                            f"(not in SSOT {sorted(_VALID_FACT_CATEGORIES)}); "
                            f"normalizing to '{_DEFAULT_FACT_CATEGORY}'."
                        )
                    category = _DEFAULT_FACT_CATEGORY

                facts.append(ExtractedFact(
                    statement=statement,
                    category=category,
                    numeric_value=_norm_optional(f.get("numeric_value")),
                    entity=_norm_optional(f.get("entity")),
                    source_citation=_norm_optional(f.get("source_citation")),
                    surprise_score=score,
                ))
            except Exception as e:
                logger.warning(f"[FactExtractor] Skipping malformed fact: {f} ({e})")
                continue

        # Preserve LLM ordering but ensure surprise_score descending for downstream consumers
        facts.sort(key=lambda x: x.surprise_score, reverse=True)

        return FactSheet(
            facts=facts,
            theme_summary=str(data.get("theme_summary", "") or "").strip(),
            extractor_reasoning=str(data.get("extractor_reasoning", "") or "").strip(),
        )
