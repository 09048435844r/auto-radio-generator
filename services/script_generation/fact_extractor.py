"""FactExtractor - Research 事実抽出エージェント（Phase 4 施策③）

Hierarchical Agentic Workflow の Step 0.5（Curator の前段）。
Perplexity のリサーチ生文字列から構造化された FactSheet を抽出し、
TopicCurator が「どのトピックが面白いか」を数値・固有名詞ベースで判断する
材料を供給する。

## アーキテクチャ（2026-05-06 から 2 段階方式）
SegmentGenerator と同型の 2 段階パターン:
  - Phase 1: LLM が **Markdown 形式** で FactSheet を生成（response_format="text"）
  - Phase 2: 正規表現で Markdown を Pydantic モデル（FactSheet）に変換

JSON 強制と FactSheet 構造化作業の同時実行が原因で発生していた問題
（JSON 切断 / enum 違反 / facts=[] 化 / tone リスト返し型）を構造的に解消する。

旧 JSON 経路のコード（_parse_fact_sheet_response 系）は呼び出しを削除したが、
緊急時の参照用として残置している（次回 PR で完全削除予定）。

## TopicCurator / ShowRunner との関係
  - ILLMPort 経由で provider-agnostic
  - PromptManager から system_prompt を取得（fact_extractor_creative）
  - last_usage でトークン使用量を公開（Phase 1 + Phase 2 合算）
  - last_fact_sheet でパイプライン層からの永続化を可能にする

後方互換性:
  - fact_extractor.enabled=False ならこのエージェントは一切呼ばれず、
    TopicCurator は fact_sheet=None で従来通り動作する。
"""
import json
import logging
import re
from pathlib import Path
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

# PR-G: extractor_reasoning に件数言及（"N 件"/"N個"/"N つ"）があるかを検出する正規表現。
# qwen3:8b が「N 件抽出した」と reasoning に書きながら facts 配列を空のまま返す
# 自己矛盾型出力（PR-E のプロンプト改善でも残存している既知症状）を検出するために使う。
# 半角・全角スペースのいずれにもマッチ。
_REASONING_COUNT_PATTERN = re.compile(r"\d+\s*[件個つ]")


class FactExtractor:
    """Research 事実抽出エージェント

    TopicCurator と同じ軽量モデルで動作する想定。
    1回の LLM 呼び出しで FactSheet を生成する。
    """

    def __init__(
        self,
        llm_port: ILLMPort,
        config: AppConfig,
        markdown_output_dir: Optional[Path] = None,
    ):
        """Initialize FactExtractor with LLM port

        Args:
            llm_port: LLM port interface for provider-agnostic communication
            config: Application configuration
            markdown_output_dir: Optional directory to save Phase 1 markdown output
                                 (fact_sheet_phase1.md). 通常は session_dir を渡す。
        """
        self._llm = llm_port
        self.config = config
        self.prompt_manager = PromptManager()
        self.markdown_output_dir = markdown_output_dir

        orch_cfg = config.yaml.script_generator.orchestrator
        # FactExtractor config (backward compatible: falls back to curator_model if not set)
        fe_cfg = getattr(orch_cfg, "fact_extractor", None)
        self.fact_extractor_model = (getattr(fe_cfg, "model", "") or "").strip() or orch_cfg.curator_model
        self.max_facts = int(getattr(fe_cfg, "max_facts", 30) or 30)
        # Phase 4 review #7: max_tokens is now config-driven so production can scale it
        # independently of max_facts without a code change.
        # 2026-05-06: 8192 → 12288 にバンプ済（2 段階移行で markdown 出力が長くなるため）
        self.max_tokens = int(getattr(fe_cfg, "max_tokens", 12288) or 12288)

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
            f"[cyan]📋 ファクト抽出開始 (2 段階モード) "
            f"(プロバイダー: {self._llm.provider_name}, モデル: {self.fact_extractor_model})[/cyan]"
        )
        log(f"  リサーチデータ: {len(content)}文字 → 最大 {self.max_facts} ファクトを抽出")

        # 2026-05-06: 2 段階アーキテクチャに移行。Phase 1 で markdown 生成、
        # Phase 2 で正規表現による FactSheet 復元。SegmentGenerator と同型。
        try:
            log("[dim]  Phase 1: Markdown 形式でファクト抽出中...[/dim]")
            markdown_text, usage = await self._generate_creative_markdown(
                theme=theme,
                research_data=research_data,
            )
            self.last_usage = usage

            # Phase 1 出力を session 配下に保存（デバッグ・HITL 参照用）
            self._save_markdown_fact_sheet(markdown_text)

            log("[dim]  Phase 2: 正規表現で FactSheet に変換中...[/dim]")
            result = self._parse_markdown_to_fact_sheet(markdown_text)

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
        # PR-F: logger.error も併用して PR-C の processing_log.txt 収集に乗せる。
        if response.finish_reason == "length":
            msg = (
                "FactExtractor output was truncated (finish_reason=length). "
                f"Current max_tokens={self.max_tokens}. "
                "Increase fact_extractor.max_tokens in config.yaml or lower max_facts. "
                "Aborting rather than returning a partial FactSheet."
            )
            logger.error(msg)
            raise RuntimeError(msg)

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
        for raw_f in data.get("facts", []) or []:
            # 2026-05-03: LLM が `facts: [{...}, ...]` ではなく `facts: ["fact1 string", ...]`
            # と string list 形式で返すケースに対応。dict.get() を呼ぶ前に正規化する。
            # 旧コードでは raw_f が str の場合に AttributeError が発生し、try/except 全体で
            # silent skip されて facts=[] になる症状があった（Qwen3-Next-80B 等で観測）。
            if isinstance(raw_f, str):
                logger.warning(
                    "[FactExtractor] facts entry was string, normalizing to "
                    "dict({statement: raw}): %r",
                    raw_f[:80],
                )
                f = {"statement": raw_f}
            elif isinstance(raw_f, dict):
                f = raw_f
            else:
                logger.warning(
                    "[FactExtractor] Skipping unexpected facts entry type %s: %r",
                    type(raw_f).__name__, raw_f,
                )
                continue
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
                # LLM が SSOT（prompts.yaml の 9 カテゴリ）以外を返した場合、
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

        theme_summary = str(data.get("theme_summary", "") or "").strip()
        extractor_reasoning = str(data.get("extractor_reasoning", "") or "").strip()

        # PR-G: 自己矛盾検出。本運用 (output/20260424_220840) で qwen3:8b が
        # extractor_reasoning に「数値系ファクト 5 件を抽出」と書きながら
        # facts 配列を空のまま返す症状が観測された。PR-E のプロンプト改善でも
        # 残存している小型モデルの構造化出力能力限界。
        #
        # ここで RuntimeError を送出することで:
        #   1. PR-C/F の logger.error 経由で processing_log.txt に症状が可視化される
        #   2. orchestrator の except Exception で fact_sheet=None にフォールスルー
        #   3. 次回本運用で発生頻度を観察して PR-G の効果測定が可能になる
        #
        # 偽陽性回避: facts に 1 件以上ある場合、または extractor_reasoning が空 or
        # 件数言及が無い場合（例: "判断材料となるファクトが見当たらず" 等）はスキップ。
        if not facts and extractor_reasoning and _REASONING_COUNT_PATTERN.search(extractor_reasoning):
            msg = (
                "FactExtractor self-inconsistency detected: facts=[] but extractor_reasoning "
                f"claims extraction. reasoning={extractor_reasoning!r}. "
                "This is a known qwen3:8b structured-output limitation symptom "
                "(reasoning written but JSON array not populated). "
                "See BACKLOG: Ollama Structured Output / model upgrade as long-term fix."
            )
            logger.error(msg)
            raise RuntimeError(msg)

        return FactSheet(
            facts=facts,
            theme_summary=theme_summary,
            extractor_reasoning=extractor_reasoning,
        )

    # ------------------------------------------------------------------
    # 2026-05-06: 2 段階アーキテクチャ移行
    # Phase 1 (markdown 生成) + Phase 2 (regex parser) + 永続化ヘルパー
    # SegmentGenerator と同型のパターン
    # ------------------------------------------------------------------

    async def _generate_creative_markdown(
        self,
        theme: str,
        research_data: "ResearchResult",
    ) -> tuple[str, LLMUsage]:
        """Phase 1: LLM に Markdown 形式で FactSheet を生成させる。

        - response_format="text"（JSON 不要、自由記述で構造化作業を分離）
        - temperature=0.2（事実抽出は低温度で安定性重視、既存値維持）
        - finish_reason="length" は fail-fast（部分 markdown を後段に流さない）
        """
        system_prompt = self.prompt_manager.get_prompt("orchestrator", "fact_extractor_creative")
        user_prompt = self._build_fact_extractor_user_prompt(theme, research_data)

        # Defensive: provider/model mismatch detection (existing pattern)
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
            max_tokens=self.max_tokens,
            temperature=0.2,
            response_format="text",  # ← JSON モードを使わず markdown 自由記述
        )

        response = await self._llm.generate(request)

        if response.finish_reason == "length":
            msg = (
                "FactExtractor Phase 1 (Markdown) output was truncated (finish_reason=length). "
                f"Current max_tokens={self.max_tokens}. "
                "Increase fact_extractor.max_tokens in config.yaml or lower max_facts. "
                "Aborting rather than passing partial Markdown to Phase 2."
            )
            logger.error(msg)
            raise RuntimeError(msg)

        logger.debug(
            f"FactExtractor Phase 1: provider={response.usage.provider}, "
            f"model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        return response.content, response.usage

    def _parse_markdown_to_fact_sheet(self, markdown_text: str) -> FactSheet:
        """Phase 2: Markdown を正規表現でパースして FactSheet を構築する。

        パース仕様:
          - "## テーマ要約" 配下のテキストを theme_summary に
          - "## 抽出方針" 配下のテキストを extractor_reasoning に
          - "### Fact N" ブロックごとにファクトを抽出
          - 各ブロックから「カテゴリ」「意外性スコア」「数値」「主語」「出典」「記述」を抽出
          - カテゴリは _VALID_FACT_CATEGORIES で検証、不一致は "その他" にフォールバック
          - 意外性スコアは 1-10 にクランプ
          - 数値・主語・出典は「なし」「N/A」「null」「-」「ー」を None に正規化
          - 記述が空のファクトはスキップ
          - 0 件マッチで ValueError（呼び出し側でフェイルオープン）

        Args:
            markdown_text: Phase 1 が生成した Markdown テキスト

        Returns:
            FactSheet: 復元された FactSheet（surprise_score 降順）

        Raises:
            ValueError: ファクトが 1 件も抽出できなかった場合
        """
        if not markdown_text or not markdown_text.strip():
            raise ValueError(
                "FactExtractor Phase 2: Markdown text is empty. "
                "Phase 1 returned empty content."
            )

        # ----- セクション抽出: "## テーマ要約" / "## 抽出方針" -----
        theme_summary = self._extract_md_section(markdown_text, "テーマ要約")
        extractor_reasoning = self._extract_md_section(markdown_text, "抽出方針")

        # ----- "### Fact N" 単位で分割 -----
        # 各 "### Fact N" 行を境界として split。先頭の見出し前部分は捨てる。
        # 数字部分はキャプチャしないため re.split を使う。
        fact_blocks = re.split(r"\n###\s*Fact\s*\d+\s*\n", "\n" + markdown_text)
        # 先頭ブロック（## テーマ要約 / ## 抽出方針 等）は捨てる
        fact_blocks = fact_blocks[1:] if len(fact_blocks) > 1 else []

        facts: list[ExtractedFact] = []
        for raw_block in fact_blocks:
            try:
                fact = self._parse_single_fact_block(raw_block)
                if fact is not None:
                    facts.append(fact)
            except Exception as e:
                # 1 つのブロック解析失敗は他に波及させない
                logger.warning(
                    "[FactExtractor] Skipping malformed Fact block: %s\nblock=%r",
                    e, raw_block[:200],
                )
                continue

        if not facts:
            # PR-G 互換: 自己矛盾検出を 2 段階モードでも保持。
            # extractor_reasoning に「N件抽出した」と書きながら facts ブロックが 0 件の
            # 場合は qwen3:8b 系の構造化能力限界症状の Phase-1-markdown 版とみなし、
            # 上位がフォールバック処理に乗せられるよう RuntimeError を送出する。
            if extractor_reasoning and _REASONING_COUNT_PATTERN.search(extractor_reasoning):
                msg = (
                    "FactExtractor self-inconsistency detected: facts=[] but extractor_reasoning "
                    f"claims extraction. reasoning={extractor_reasoning!r}. "
                    "Phase 1 markdown produced no '### Fact N' blocks despite stating a count. "
                    "This is the markdown analog of the known qwen3:8b structured-output limitation."
                )
                logger.error(msg)
                raise RuntimeError(msg)

            raise ValueError(
                "FactExtractor Phase 2: No valid Fact blocks found in Markdown. "
                "Phase 1 output may not follow the '### Fact N' format. "
                f"Markdown preview (first 500 chars): {markdown_text[:500]}"
            )

        # surprise_score 降順で並べる（Curator 側ソートに依存させない）
        facts.sort(key=lambda x: x.surprise_score, reverse=True)

        return FactSheet(
            facts=facts,
            theme_summary=theme_summary,
            extractor_reasoning=extractor_reasoning,
        )

    @staticmethod
    def _extract_md_section(markdown: str, heading: str) -> str:
        """Markdown から `## {heading}` 配下の段落を抽出する。

        次の `##` または `###` または EOF までを取得し、前後空白を trim。
        該当セクションが見つからなければ空文字列を返す（防御的）。
        """
        # `## heading` の直後から、次の `##` or `###` or EOF までを取得
        pattern = (
            r"##\s*"
            + re.escape(heading)
            + r"\s*\n(?P<body>.+?)(?=\n##\s|\n###\s|\Z)"
        )
        m = re.search(pattern, markdown, re.DOTALL)
        if not m:
            return ""
        return m.group("body").strip()

    @staticmethod
    def _normalize_optional_md_field(value: Optional[str]) -> Optional[str]:
        """「なし」「N/A」「null」「-」「ー」「（なし）」等を None に正規化する。"""
        if value is None:
            return None
        s = value.strip()
        if not s:
            return None
        # 半角・全角カッコ除去（"（なし）"対策）
        bare = s.strip("（）()[]【】 ").strip()
        if bare.lower() in {"none", "null", "n/a", "na"}:
            return None
        if bare in {"なし", "無し", "ナシ", "-", "ー", "−", "—", "—"}:
            return None
        return s

    def _parse_single_fact_block(self, block: str) -> Optional[ExtractedFact]:
        """Fact ブロック 1 個から ExtractedFact を構築する。

        ブロックは "### Fact N" 行を取り除いたあとの本文（リスト形式）。
        必要フィールド「記述」が無ければ None を返す（呼び出し側でスキップ）。
        """
        # 各フィールドを抽出する正規表現。順序問わず、行頭・末尾の空白に寛容。
        # 以下の 2 表記を許容（LLM がどちらを出力するかブレがあるため）:
        #   - `- **カテゴリ**: 値` (太字外コロン、プロンプト推奨形式)
        #   - `- **カテゴリ:** 値` (太字内コロン、よくあるドリフト)
        # 全角コロン「：」も許容。
        def _find(label: str) -> Optional[str]:
            pat = (
                r"-\s*\*\*"
                + re.escape(label)
                + r"[:：]?\*\*\s*[:：]?\s*(.+?)\s*$"
            )
            m = re.search(pat, block, re.MULTILINE)
            return m.group(1).strip() if m else None

        statement = _find("記述")
        if not statement:
            # 記述必須。無ければスキップ（前段で warning は呼び出し側ログ）
            return None

        # ----- カテゴリ -----
        raw_category = _find("カテゴリ") or ""
        # リスト返し対策（Phase 1 でも防御）: "[数値, 比較]" のような表記を first item に絞る
        raw_category = raw_category.strip("[]【】「」 ").split(",")[0].strip()
        if raw_category in _VALID_FACT_CATEGORIES:
            category: FactCategory = raw_category  # type: ignore[assignment]
        else:
            if raw_category:
                logger.warning(
                    f"[FactExtractor Phase 2] Unknown category '{raw_category}' "
                    f"(not in SSOT {sorted(_VALID_FACT_CATEGORIES)}); "
                    f"normalizing to '{_DEFAULT_FACT_CATEGORY}'."
                )
            category = _DEFAULT_FACT_CATEGORY

        # ----- 意外性スコア -----
        raw_score = _find("意外性スコア") or "5"
        # 数字以外の文字（"7点" "8 / 10" 等）からも数字部分だけ取り出す
        m_score = re.search(r"\d+", raw_score)
        try:
            score = int(m_score.group()) if m_score else 5
        except (TypeError, ValueError):
            score = 5
        score = max(1, min(10, score))

        # ----- optional フィールド -----
        numeric_value = self._normalize_optional_md_field(_find("数値"))
        entity = self._normalize_optional_md_field(_find("主語"))
        source_citation = self._normalize_optional_md_field(_find("出典"))

        return ExtractedFact(
            statement=statement,
            category=category,
            numeric_value=numeric_value,
            entity=entity,
            source_citation=source_citation,
            surprise_score=score,
        )

    def _save_markdown_fact_sheet(self, markdown_text: str) -> None:
        """Phase 1 の markdown を session ディレクトリに保存（fact_sheet_phase1.md）。

        markdown_output_dir が None なら no-op（テスト・CLI 実行時のセーフティ）。
        書き込み失敗は WARNING のみで例外を伝播させない。
        """
        if not self.markdown_output_dir:
            return
        try:
            self.markdown_output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.markdown_output_dir / "fact_sheet_phase1.md"
            output_path.write_text(markdown_text, encoding="utf-8")
            logger.debug(f"FactExtractor Phase 1 markdown saved: {output_path}")
            console.print(f"[dim]💾 Markdown saved: {output_path.name}[/dim]")
        except Exception as e:
            logger.warning(f"Failed to save fact_sheet_phase1.md (non-fatal): {e}")
