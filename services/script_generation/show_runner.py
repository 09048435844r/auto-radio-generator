"""ShowRunner - 番組構成プランナーエージェント（Phase 3 施策④）

Hierarchical Agentic Workflow の Step 1.5。
TopicCurator が選定したトピック群を受け取り、番組全体のアーク・ブリッジ・
トーン配分を設計する。後続の SegmentGenerator に ShowPlan を渡すことで、
ダイジェスト感ではなく一貫したストーリーを持つ「番組」としての台本を目指す。

TopicCurator と同型のアーキテクチャ:
  - ILLMPort 経由で provider-agnostic
  - PromptManager から system_prompt を取得
  - JSON レスポンスをサニタイズ付きでパース
  - last_usage でトークン使用量を公開


Step 4 v2 (2026-05-10) @deprecated: 旧 Gemini 自動経路の構成要素のため deprecated 扱い。
HITL タブからのみ呼ばれる。新規開発では外部台本モード (services/pipeline/external_script_phase.py)
を推奨。物理削除は Step 5 で再評価予定。
"""
import json
import logging
from typing import Optional

from rich.console import Console

from core.models import AppConfig, LLMUsage
from core.models.curation import CurationResult
from core.models.show_plan import ShowPlan, TopicBridge
from core.utils import sanitize_json_response
from core.prompt_manager import PromptManager
from core.interfaces.llm_port import ILLMPort, LLMRequest

logger = logging.getLogger(__name__)
console = Console()


class ShowRunner:
    """番組構成プランナーエージェント

    TopicCurator と同じ軽量モデルで動作する想定。
    1回の LLM 呼び出しで番組全体の構成（ShowPlan）を設計する。
    """

    def __init__(self, llm_port: ILLMPort, config: AppConfig):
        """Initialize ShowRunner with LLM port

        Args:
            llm_port: LLM port interface for provider-agnostic communication
            config: Application configuration
        """
        self._llm = llm_port
        self.config = config
        self.prompt_manager = PromptManager()

        orch_cfg = config.yaml.script_generator.orchestrator
        # ShowRunner config (backward compatible: falls back to curator_model if not set)
        sr_cfg = getattr(orch_cfg, "show_runner", None)
        self.show_runner_model = (getattr(sr_cfg, "model", "") or "").strip() or orch_cfg.curator_model
        # PR-D Issue C: max_tokens config 駆動化。旧ハードコード 4096 を既定値として踏襲
        self.max_tokens = int(getattr(sr_cfg, "max_tokens", 4096) or 4096)

        self.last_usage: Optional[LLMUsage] = None
        # Expose the last successfully-produced ShowPlan so the pipeline layer
        # can persist it without re-invoking the agent.
        self.last_show_plan: Optional[ShowPlan] = None

    async def plan_show(
        self,
        theme: str,
        curation_result: CurationResult,
        progress_log=None,
    ) -> ShowPlan:
        """Curator 出力から番組構成プラン（ShowPlan）を設計する

        Args:
            theme: 番組のテーマ
            curation_result: Curator が選定したトピック群
            progress_log: 進捗ログ関数（オプション）

        Returns:
            ShowPlan: 番組全体の構成設計

        Raises:
            ValueError: curation_result が空の場合（ShowPlan 設計不能）
            Exception: LLM 呼び出し or JSON パース失敗時
        """
        log = progress_log or (lambda msg: console.print(msg))

        topics = curation_result.topics if curation_result else []
        if not topics:
            raise ValueError("ShowRunner.plan_show: curation_result has no topics to plan around")

        log(
            f"[cyan]🎬 番組構成設計開始 "
            f"(プロバイダー: {self._llm.provider_name}, モデル: {self.show_runner_model})[/cyan]"
        )
        log(f"  対象トピック数: {len(topics)}")

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "show_runner")
        user_prompt = self._build_show_runner_user_prompt(theme, curation_result)

        try:
            response_text, usage = await self._call_api(system_prompt, user_prompt)
            self.last_usage = usage
            result = self._parse_show_plan_response(response_text, topic_count=len(topics))

            log(f"[green]✓ 番組構成設計完了[/green]")
            log(f"  アーク: {result.overall_arc[:60]}...")
            log(f"  トーン: {result.overall_tone}")
            log(f"  ブリッジ数: {len(result.topic_bridges)}")
            self.last_show_plan = result
            return result

        except Exception as e:
            log(f"[red]✗ 番組構成設計エラー: {e}[/red]")
            logger.error(f"ShowRunner.plan_show failed: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Internal: prompt building
    # ------------------------------------------------------------------

    def _build_show_runner_user_prompt(
        self,
        theme: str,
        curation_result: CurationResult,
    ) -> str:
        """ShowRunner 用ユーザープロンプトを構築"""
        prompt = f"## テーマ\n{theme}\n\n"
        prompt += f"## Curator が選定したトピック一覧（{len(curation_result.topics)}件）\n"
        for i, topic in enumerate(curation_result.topics):
            # Defensive: selection_reason may be empty on older data
            selection_reason = (getattr(topic, "selection_reason", "") or "").strip()
            key_facts = getattr(topic, "key_facts", None) or []
            facts_preview = "、".join(
                [str(f) for f in key_facts[:3] if isinstance(f, str) and f.strip()]
            )
            prompt += f"\n### トピック {i}（0始まりインデックス）\n"
            prompt += f"- title: {topic.title}\n"
            prompt += f"- tone: {topic.tone}\n"
            if selection_reason:
                prompt += f"- selection_reason: {selection_reason}\n"
            if facts_preview:
                prompt += f"- key_facts (抜粋): {facts_preview}\n"

        if curation_result.curator_reasoning:
            prompt += f"\n## Curator の総評\n{curation_result.curator_reasoning}\n"

        # Compute expected bridge count: N+1 (intro→0, 0→1, ..., N-1→conclusion)
        expected_bridges = len(curation_result.topics) + 1

        prompt += (
            f"\n## 指示\n"
            f"上記を踏まえ、番組全体の構成プランを設計してください。\n"
            f"topic_bridges は以下の {expected_bridges} 本を必ず含めること:\n"
            f"  - from_topic_index=-1, to_topic_index=0 （導入 → 最初の深掘り）\n"
        )
        for i in range(len(curation_result.topics) - 1):
            prompt += f"  - from_topic_index={i}, to_topic_index={i + 1} （深掘り{i}→深掘り{i + 1}）\n"
        prompt += (
            f"  - from_topic_index={len(curation_result.topics) - 1}, to_topic_index=-1 "
            f"（最終深掘り → まとめ）\n\n"
        )

        prompt += (
            "## 出力形式（JSON）\n"
            "**重要**: 以下の形式で有効なJSONのみを出力してください。\n"
            "- コードブロック（```json）は使用しないこと\n"
            "- 文字列内の改行は使用せず、すべて1行で記述すること\n\n"
            "{\n"
            '  "overall_arc": "番組全体のストーリーアーク（80〜150文字、起伏・驚きの配置を具体的に）",\n'
            '  "intro_hook_strategy": "導入で視聴者を掴む切り口（例: \'冒頭3ターンで最大の数字を提示\'）",\n'
            '  "topic_bridges": [\n'
            '    {"from_topic_index": -1, "to_topic_index": 0, "transition_hint": "〜という切り口で最初の深掘りへ誘う"},\n'
            '    {"from_topic_index": 0, "to_topic_index": 1, "transition_hint": "対比を強調してトピック1へ"}\n'
            '  ],\n'
            '  "conclusion_strategy": "締めの設計（視聴者に何を持ち帰らせるか、余韻の残し方）",\n'
            '  "overall_tone": "トーン配分の方針（例: \'驚き多め、ユーモア控えめ、最後だけ余韻重視\'）",\n'
            '  "planner_reasoning": "この構成にした理由（200文字程度、改行なし）"\n'
            "}\n"
        )
        return prompt

    # ------------------------------------------------------------------
    # Internal: API call (same pattern as TopicCurator)
    # ------------------------------------------------------------------

    async def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, LLMUsage]:
        """Call LLM API for show planning"""
        # Defensive: if configured model looks Ollama-specific but provider isn't Ollama, fall back
        model_to_use = self.show_runner_model
        if model_to_use and self._llm.provider_name != "ollama":
            if ":" in model_to_use or model_to_use.startswith("ollama/"):
                logger.warning(
                    f"show_runner.model '{model_to_use}' appears to be Ollama-specific "
                    f"but provider is '{self._llm.provider_name}'. Using provider default."
                )
                model_to_use = None

        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model_to_use,
            max_tokens=self.max_tokens,  # PR-D: config 駆動（旧ハードコード 4096）
            temperature=0.4,   # Slightly higher than curator to encourage creative arc design
            response_format="json",
        )

        response = await self._llm.generate(request)

        # PR-D Issue C: fail-fast on truncation. Orchestrator catches the raise and
        # falls back to show_plan=None, so downstream segment generation continues
        # without ShowPlan hints (backward-compatible behavior).
        # PR-F: logger.error も併用して PR-C の processing_log.txt 収集に乗せる。
        if response.finish_reason == "length":
            msg = (
                "ShowRunner output was truncated (finish_reason=length). "
                f"Current max_tokens={self.max_tokens}. "
                "Increase orchestrator.show_runner.max_tokens in config.yaml. "
                "Aborting rather than returning a partial ShowPlan."
            )
            logger.error(msg)
            raise RuntimeError(msg)

        logger.debug(
            f"ShowRunner API: provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        return response.content, response.usage

    # ------------------------------------------------------------------
    # Internal: response parsing (same pattern as TopicCurator)
    # ------------------------------------------------------------------

    def _parse_show_plan_response(self, response_text: str, topic_count: int) -> ShowPlan:
        """APIレスポンスを ShowPlan に変換。失敗時は sanitize を試行。"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError as e:
            logger.error(f"[ShowRunner] JSON parse error: {e}")
            logger.error(
                f"[ShowRunner] Full raw response text ({len(response_text)} chars):\n"
                f"{'=' * 80}\n{response_text}\n{'=' * 80}"
            )
            console.print("[yellow]⚠️ ShowRunner JSONパースエラー。サニタイズ処理を試行中...[/yellow]")
            cleaned = sanitize_json_response(response_text, "ShowRunner")
            try:
                data = json.loads(cleaned, strict=False)
                console.print("[green]✓ サニタイズ後のパースに成功[/green]")
            except json.JSONDecodeError as e2:
                logger.error(f"[ShowRunner] JSON parse failed after sanitization: {e2}")
                console.print("[red]✗ ShowRunner: サニタイズ後もJSONパース失敗[/red]")
                raise

        # Parse bridges defensively
        bridges: list[TopicBridge] = []
        for br in data.get("topic_bridges", []) or []:
            try:
                bridges.append(TopicBridge(
                    from_topic_index=int(br.get("from_topic_index", -1)),
                    to_topic_index=int(br.get("to_topic_index", -1)),
                    transition_hint=str(br.get("transition_hint", "") or "").strip(),
                ))
            except (TypeError, ValueError) as e:
                logger.warning(f"[ShowRunner] Skipping invalid bridge: {br} ({e})")
                continue

        show_plan = ShowPlan(
            overall_arc=str(data.get("overall_arc", "") or "").strip(),
            intro_hook_strategy=str(data.get("intro_hook_strategy", "") or "").strip(),
            topic_bridges=bridges,
            conclusion_strategy=str(data.get("conclusion_strategy", "") or "").strip(),
            overall_tone=str(data.get("overall_tone", "") or "").strip(),
            planner_reasoning=str(data.get("planner_reasoning", "") or "").strip(),
        )

        # Soft validation: warn (but don't fail) if bridges don't cover all transitions
        expected = topic_count + 1  # intro→0, ..., N-1→conclusion
        if len(show_plan.topic_bridges) < expected:
            logger.warning(
                f"[ShowRunner] Expected {expected} bridges for {topic_count} topics, "
                f"got {len(show_plan.topic_bridges)}. SegmentGenerator will fall back "
                f"to default transitions for missing bridges."
            )

        return show_plan
