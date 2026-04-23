"""TopicCurator - リサーチデータから面白いトピックを選定するエージェント

Hierarchical Agentic Workflow の Step 1。
膨大なリサーチデータを受け取り、ずんだもんとめたんが深く語り合うべき
2〜3個のトピックを意外性・具体性・議論性の3軸で評価・選定する。
"""
import asyncio
import json
import logging
from typing import Optional, TYPE_CHECKING

from rich.console import Console
from pydantic import BaseModel, Field

from core.models import AppConfig, LLMUsage
from core.utils import sanitize_json_response
from core.models.curation import CuratedTopic, CurationResult
from core.prompt_manager import PromptManager
from core.interfaces.llm_port import ILLMPort, LLMRequest

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult
    from core.models.fact_sheet import FactSheet

logger = logging.getLogger(__name__)
console = Console()


class TopicCurator:
    """リサーチデータから面白いトピックを選定するエージェント

    軽量モデル（gemini-2.5-flash 等）を使用してコストを抑えながら、
    後続の SegmentGenerator に渡す「厳選済みトピック」を生成する。
    """

    def __init__(self, llm_port: ILLMPort, config: AppConfig):
        """Initialize TopicCurator with LLM port
        
        Args:
            llm_port: LLM port interface for provider-agnostic communication
            config: Application configuration
        """
        self._llm = llm_port
        self.config = config
        self.prompt_manager = PromptManager()

        # オーケストレーター設定からキュレーター用モデルを取得
        orch_cfg = config.yaml.script_generator.orchestrator
        self.curator_model = orch_cfg.curator_model
        self.max_topics = orch_cfg.max_topics

        self.last_usage: Optional[LLMUsage] = None

    async def curate_topics(
        self,
        research_data: "ResearchResult",
        target_count: Optional[int] = None,
        progress_log=None,
        fact_sheet: Optional["FactSheet"] = None,
    ) -> CurationResult:
        """リサーチデータから面白いトピックを選定する

        Args:
            research_data: Perplexityから得たリサーチ結果
            target_count: 選定するトピック数（Noneの場合は設定値を使用）
            progress_log: 進捗ログ関数（オプション）
            fact_sheet: Phase 4 施策③で生成された構造化ファクトシート（オプション）。
                        渡された場合はユーザープロンプトに差し込み、Curator の判断精度を上げる。
                        None の場合は従来通りリサーチ生文字列のみで動作（後方互換）。

        Returns:
            CurationResult: 選定されたトピックと選定理由
        """
        count = target_count or self.max_topics
        log = progress_log or (lambda msg: console.print(msg))

        log(f"[cyan]🔍 トピックキュレーション開始 (プロバイダー: {self._llm.provider_name}, モデル: {self.curator_model})[/cyan]")
        log(f"  リサーチデータ: {len(research_data.content)}文字 → {count}トピックを選定")
        if fact_sheet is not None and not fact_sheet.is_empty():
            log(f"  FactSheet: {len(fact_sheet.facts)}件のファクトを判断材料として使用")

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "curation")
        user_prompt = self._build_curation_user_prompt(research_data, count, fact_sheet=fact_sheet)

        try:
            response_text, usage = await self._call_api(system_prompt, user_prompt)
            self.last_usage = usage
            result = self._parse_curation_response(response_text)

            log(f"[green]✓ キュレーション完了: {len(result.topics)}トピック選定[/green]")
            for i, topic in enumerate(result.topics, 1):
                log(f"  {i}. {topic.title} (推定{topic.estimated_turns}ターン, tone={topic.tone})")

            return result

        except Exception as e:
            log(f"[red]✗ キュレーションエラー: {e}[/red]")
            logger.error(f"TopicCurator.curate_topics failed: {e}", exc_info=True)
            raise

    def _build_curation_user_prompt(
        self,
        research_data: "ResearchResult",
        target_count: int,
        fact_sheet: Optional["FactSheet"] = None,
    ) -> str:
        """キュレーション用ユーザープロンプトを構築"""
        prompt = f"## テーマ\n{research_data.mode}モードでリサーチされたデータです。\n\n"
        prompt += f"## リサーチデータ（全文）\n{research_data.content}\n\n"

        # Phase 4: FactSheet が提供されていれば、構造化ファクトを差し込む
        # これにより Curator は数値・固有名詞ベースで選定判断を行える
        if fact_sheet is not None and not fact_sheet.is_empty():
            prompt += "## 構造化ファクトシート（FactExtractor による事前分析）\n"
            if fact_sheet.theme_summary:
                prompt += f"### テーマ要約\n{fact_sheet.theme_summary}\n\n"
            top_facts = fact_sheet.top_facts(limit=min(20, len(fact_sheet.facts)))
            if top_facts:
                prompt += f"### 意外性の高いファクト（上位{len(top_facts)}件、surprise_score 降順）\n"
                for i, fact in enumerate(top_facts, 1):
                    meta_parts: list[str] = [f"surprise={fact.surprise_score}", f"cat={fact.category}"]
                    if fact.numeric_value:
                        meta_parts.append(f"数値={fact.numeric_value}")
                    if fact.entity:
                        meta_parts.append(f"主語={fact.entity}")
                    prompt += f"{i}. [{' / '.join(meta_parts)}] {fact.statement}\n"
                prompt += "\n"
            prompt += (
                "**重要**: 上記ファクトシートの意外性スコアと固有名詞を参考に、"
                "key_facts を具体化し、selection_reason で「なぜこのトピックが面白いか」を"
                "数字・固有名詞ベースで書くこと。\n\n"
            )

        prompt += (
            f"## 指示\n"
            f"上記のリサーチデータから、最も面白い**{target_count}個**のトピックを選定してください。\n"
            f"評価軸（意外性・具体性・議論性）で採点し、上位{target_count}個を選ぶこと。\n\n"
            f"## 出力形式（JSON）\n"
            f"**重要**: 以下の形式で有効なJSONのみを出力してください。\n"
            f"- コードブロック（```json）は使用しないこと\n"
            f"- 文字列内の改行は使用せず、すべて1行で記述すること\n"
            f"- ダブルクォートは必ずエスケープすること\n\n"
            f"{{\n"
            f'  "topics": [\n'
            f'    {{\n'
            f'      "title": "トピックタイトル",\n'
            f'      "content": "詳細情報（500〜800文字、改行なし）",\n'
            f'      "priority": 1,\n'
            f'      "estimated_turns": 30,\n'
            f'      "tone": "驚き",\n'
            f'      "key_facts": ["ファクト1", "ファクト2", "ファクト3"],\n'
            f'      "selection_reason": "なぜこのトピックが面白いのか80〜120文字で（切り口の核心を具体的に）"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "curator_reasoning": "選定理由（デバッグ用、改行なし）"\n'
            f"}}\n"
        )
        return prompt

    async def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, LLMUsage]:
        """LLM API を呼び出してキュレーション結果を取得"""
        # Determine model to use: if curator_model is Ollama-specific and provider is not Ollama, use None (default)
        model_to_use = self.curator_model
        if model_to_use and self._llm.provider_name != "ollama":
            # Detect Ollama-specific patterns: "model:tag" or "ollama/model"
            if ":" in model_to_use or model_to_use.startswith("ollama/"):
                logger.warning(
                    f"curator_model '{model_to_use}' appears to be Ollama-specific but provider is '{self._llm.provider_name}'. "
                    f"Using provider's default model instead."
                )
                model_to_use = None
        
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model_to_use,
            max_tokens=8192,  # JSON途中切断を防ぐため増量
            temperature=0.3,  # キュレーションは低温度で安定性を確保
            response_format="json"
        )
        
        response = await self._llm.generate(request)
        
        # Warn if output was truncated
        if response.finish_reason == "length":
            logger.warning(
                f"⚠️ TopicCurator output was truncated (finish_reason=length). "
                f"Consider increasing max_output_tokens."
            )
        
        logger.debug(
            f"TopicCurator API: provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        
        return response.content, response.usage

    def _parse_curation_response(self, response_text: str) -> CurationResult:
        """APIレスポンスを CurationResult に変換"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError as e:
            # JSONパースエラー時の詳細ログ（デバッグ用）
            logger.error(f"[TopicCurator] JSON parse error: {e}")
            logger.error(f"[TopicCurator] Error position: line {e.lineno}, column {e.colno}, char {e.pos}")
            
            # 完全な生のレスポンステキストを出力（重要：人間がエラー箇所を特定できるように）
            logger.error(f"[TopicCurator] Full raw response text ({len(response_text)} chars):\n{'='*80}\n{response_text}\n{'='*80}")
            
            # 強力なサニタイズ処理を試行
            console.print(f"[yellow]⚠️ JSONパースエラー。サニタイズ処理を試行中...[/yellow]")
            cleaned = sanitize_json_response(response_text, "TopicCurator")
            logger.debug(f"[TopicCurator] Sanitized text ({len(cleaned)} chars):\n{cleaned[:1000]}...")
            
            try:
                data = json.loads(cleaned, strict=False)
                console.print(f"[green]✓ サニタイズ後のパースに成功[/green]")
            except json.JSONDecodeError as e2:
                logger.error(f"[TopicCurator] JSON parse failed after sanitization: {e2}")
                logger.error(f"[TopicCurator] Sanitized text:\n{'='*80}\n{cleaned}\n{'='*80}")
                console.print(f"[red]✗ サニタイズ後もJSONパースに失敗しました[/red]")
                console.print(f"[red]生のレスポンステキストをログファイルで確認してください[/red]")
                raise

        topics_data = data.get("topics", [])
        topics = []
        for t in topics_data:
            # Defensive: some local LLMs (e.g. qwen3:8b) occasionally omit the `title`
            # field even though content / key_facts / selection_reason are populated.
            # In that case, synthesize a usable title so downstream ShowRunner and
            # SegmentGenerator have a non-empty label to reference.
            raw_title = (t.get("title", "") or "").strip()
            if not raw_title:
                key_facts = t.get("key_facts", []) or []
                first_fact = next(
                    (str(f).strip() for f in key_facts if isinstance(f, str) and f.strip()),
                    "",
                )
                fallback_source = first_fact or (t.get("selection_reason", "") or "").strip()
                if fallback_source:
                    raw_title = fallback_source[:40].rstrip("、。 ")
                    logger.warning(
                        f"[TopicCurator] LLM omitted 'title'; synthesized from fallback: {raw_title!r}"
                    )
                else:
                    raw_title = f"トピック{len(topics) + 1}"
                    logger.warning(
                        f"[TopicCurator] LLM omitted both 'title' and fallback sources; "
                        f"using placeholder: {raw_title!r}"
                    )

            topics.append(CuratedTopic(
                title=raw_title,
                content=t.get("content", ""),
                priority=t.get("priority", len(topics) + 1),
                estimated_turns=t.get("estimated_turns", 30),
                tone=t.get("tone", "解説"),
                key_facts=t.get("key_facts", []),
                # Backward compatible: older LLM responses may not include selection_reason
                selection_reason=t.get("selection_reason", "") or "",
            ))

        # 優先度でソート
        topics.sort(key=lambda x: x.priority)

        return CurationResult(
            topics=topics,
            curator_reasoning=data.get("curator_reasoning", ""),
        )

