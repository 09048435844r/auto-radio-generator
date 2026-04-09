"""SegmentGenerator - 台本の1セグメントを生成するエージェント

Hierarchical Agentic Workflow の Step 2。
TopicCuratorが選定したトピックを受け取り、セグメントタイプ
（intro / deep_dive / conclusion）に応じた台本を生成する。
前セグメントの文脈要約を受け取り、会話の連続性を維持する。
"""
import asyncio
import json
import logging
from typing import Optional, TYPE_CHECKING

from rich.console import Console

from core.models import AppConfig, LLMUsage
from core.models.curation import CuratedTopic, ScriptSegment
from core.prompt_manager import PromptManager
from core.utils import sanitize_json_response
from core.interfaces.llm_port import ILLMPort, LLMRequest

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
console = Console()


class SegmentGenerator:
    """１つの台本セグメントを生成するエージェント

    各セグメントは独立したAPI呼び出しで生成されるため、
    max_output_tokens の壁を回避できる。
    セグメントタイプに応じた専用プロンプトを使用する。
    """

    def __init__(self, llm_port: ILLMPort, config: AppConfig):
        """Initialize SegmentGenerator with LLM port
        
        Args:
            llm_port: LLM port interface for provider-agnostic communication
            config: Application configuration
        """
        self._llm = llm_port
        self.config = config
        self.prompt_manager = PromptManager()

        orch_cfg = config.yaml.script_generator.orchestrator

        # セグメント生成用モデル（空の場合はportのデフォルトモデルを使用）
        self.segment_model = orch_cfg.segment_model or llm_port.model_name

        # セグメント別ターン数設定
        self.intro_cfg = orch_cfg.intro
        self.deep_dive_cfg = orch_cfg.deep_dive
        self.conclusion_cfg = orch_cfg.conclusion

        self.last_usage: Optional[LLMUsage] = None

    async def generate_intro(
        self,
        theme: str,
        topic_titles: list[str],
        context: str = "",
        progress_log=None,
    ) -> ScriptSegment:
        """番組導入部セグメントを生成

        Args:
            theme: 番組のテーマ
            topic_titles: これから扱うトピックのタイトル一覧
            context: 前セグメントの文脈要約（通常は空）
            progress_log: 進捗ログ関数
        """
        log = progress_log or (lambda msg: console.print(msg))
        log(f"[cyan]📝 導入セグメント生成中...[/cyan]")

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "segment_intro").format(
            min_turns=self.intro_cfg.min_turns,
            max_turns=self.intro_cfg.max_turns,
        )
        user_prompt = self._build_intro_user_prompt(theme, topic_titles, context)

        response_text, usage = await self._call_api(system_prompt, user_prompt)
        self.last_usage = usage
        segment = self._parse_segment_response(response_text, expected_type="intro")

        log(f"[green]  ✓ 導入: {len(segment.turns)}ターン[/green]")
        return segment

    async def generate_deep_dive(
        self,
        topic: CuratedTopic,
        segment_index: int,
        context: str,
        progress_log=None,
    ) -> ScriptSegment:
        """深掘りセグメントを生成

        Args:
            topic: キュレーション済みトピック
            segment_index: 深掘りセグメントの番号（1始まり）
            context: 前セグメントの文脈要約
            progress_log: 進捗ログ関数
        """
        log = progress_log or (lambda msg: console.print(msg))
        log(f"[cyan]📝 深掘りセグメント{segment_index}生成中: 「{topic.title}」[/cyan]")

        segment_id = f"deep_dive_{segment_index}"
        section_marker = f"main_{segment_index}" if segment_index > 1 else "main"

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "segment_deep_dive").format(
            context=context or "（前のセグメントはありません。これが番組の最初です）",
            min_turns=self.deep_dive_cfg.min_turns,
            max_turns=self.deep_dive_cfg.max_turns,
            segment_id=segment_id,
            topic_title=topic.title,
            section_marker=section_marker,
        )
        user_prompt = self._build_deep_dive_user_prompt(topic)

        response_text, usage = await self._call_api(system_prompt, user_prompt)
        self.last_usage = usage
        segment = self._parse_segment_response(response_text, expected_type="deep_dive")

        log(f"[green]  ✓ 深掘り{segment_index}「{topic.title}」: {len(segment.turns)}ターン[/green]")
        return segment

    async def generate_conclusion(
        self,
        theme: str,
        topic_titles: list[str],
        context: str,
        progress_log=None,
    ) -> ScriptSegment:
        """まとめセグメントを生成

        Args:
            theme: 番組のテーマ
            topic_titles: 今日扱ったトピックのタイトル一覧
            context: 前セグメントの文脈要約
            progress_log: 進捗ログ関数
        """
        log = progress_log or (lambda msg: console.print(msg))
        log(f"[cyan]📝 まとめセグメント生成中...[/cyan]")

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "segment_conclusion").format(
            context=context or "（文脈情報なし）",
            min_turns=self.conclusion_cfg.min_turns,
            max_turns=self.conclusion_cfg.max_turns,
        )
        user_prompt = self._build_conclusion_user_prompt(theme, topic_titles)

        response_text, usage = await self._call_api(system_prompt, user_prompt)
        self.last_usage = usage
        segment = self._parse_segment_response(response_text, expected_type="conclusion")

        log(f"[green]  ✓ まとめ: {len(segment.turns)}ターン[/green]")
        return segment

    # ------------------------------------------------------------------
    # User prompt builders
    # ------------------------------------------------------------------

    def _build_intro_user_prompt(
        self, theme: str, topic_titles: list[str], context: str
    ) -> str:
        topics_preview = "\n".join(f"- {t}" for t in topic_titles)
        prompt = f"## テーマ\n{theme}\n\n"
        prompt += f"## 今日深掘りするトピック（予告用）\n{topics_preview}\n\n"
        if context:
            prompt += f"## 引き継ぎ文脈\n{context}\n\n"
        prompt += "上記の情報をもとに、番組の導入部（イントロ）を生成してください。"
        return prompt

    def _build_deep_dive_user_prompt(self, topic: CuratedTopic) -> str:
        prompt = f"## 深掘りするトピック\n**{topic.title}**\n\n"
        prompt += f"## トピックの詳細情報\n{topic.content}\n\n"
        if topic.key_facts:
            facts = "\n".join(f"- {f}" for f in topic.key_facts)
            prompt += f"## 必ず会話に織り込むべきキーファクト\n{facts}\n\n"
        prompt += f"## 推奨トーン\n{topic.tone}\n\n"
        prompt += (
            "上記のトピックについて、深掘りセグメントを生成してください。\n"
            "key_factsに含まれる情報はすべて会話に織り込むこと。"
        )
        return prompt

    def _build_conclusion_user_prompt(
        self, theme: str, topic_titles: list[str]
    ) -> str:
        topics_list = "\n".join(f"- {t}" for t in topic_titles)
        prompt = f"## テーマ\n{theme}\n\n"
        prompt += f"## 今日扱ったトピック\n{topics_list}\n\n"
        prompt += "上記をふまえて、番組のまとめとエンディングを生成してください。"
        return prompt

    # ------------------------------------------------------------------
    # API call
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        model_override: Optional[str] = None,
    ) -> tuple[str, LLMUsage]:
        """Call LLM API via port interface"""
        model_to_use = model_override or self.segment_model
        
        console.print(
            f"[dim]SegmentGenerator API: provider={self._llm.provider_name}, model={model_to_use}, max_tokens=8192[/dim]"
        )
        
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model_to_use,
            max_tokens=8192,  # 1セグメント分は 8K で十分
            temperature=0.85,
            response_format="json"
        )
        
        response = await self._llm.generate(request)
        
        # Warn if output was truncated
        if response.finish_reason == "length":
            logger.warning(
                f"SegmentGenerator: MAX_TOKENS に到達。出力が切り詰められた可能性あり (model={model_to_use})"
            )
        
        logger.debug(
            f"SegmentGenerator API: provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        
        return response.content, response.usage

    # ------------------------------------------------------------------
    # Response parser
    # ------------------------------------------------------------------

    def _parse_segment_response(
        self, response_text: str, expected_type: str
    ) -> ScriptSegment:
        """APIレスポンスを ScriptSegment に変換"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError as e:
            logger.error(f"[SegmentGenerator] JSON parse error: {e}")
            logger.error(f"[SegmentGenerator] Error position: line {e.lineno}, column {e.colno}")
            logger.debug(f"[SegmentGenerator] Raw response ({len(response_text)} chars):\n{response_text[:1000]}...")
            
            console.print(f"[yellow]⚠️ JSONパースエラー。サニタイズ処理を試行中...[/yellow]")
            cleaned = sanitize_json_response(response_text, "SegmentGenerator")
            
            try:
                data = json.loads(cleaned, strict=False)
                console.print(f"[green]✓ サニタイズ後のパースに成功[/green]")
            except json.JSONDecodeError as e2:
                logger.error(f"[SegmentGenerator] JSON parse failed after sanitization: {e2}")
                logger.error(f"[SegmentGenerator] Sanitized text:\n{'='*80}\n{cleaned}\n{'='*80}")
                console.print(f"[red]✗ サニタイズ後もJSONパースに失敗しました[/red]")
                raise

        turns_raw = data.get("turns", [])

        # speaker_id -> speaker の後方互換変換
        turns = []
        for t in turns_raw:
            if "speaker_id" in t and "speaker" not in t:
                sid = t.pop("speaker_id")
                t["speaker"] = "A" if sid == "main" else "B"
            turns.append(t)

        return ScriptSegment(
            segment_id=data.get("segment_id", expected_type),
            segment_type=data.get("segment_type", expected_type),
            topic_title=data.get("topic_title"),
            turns=turns,
            context_summary=data.get("context_summary", ""),
            token_count=0,
        )

