"""ScriptOrchestrator - 台本生成の全体統括エージェント

Hierarchical Agentic Workflow の司令塔。
1. TopicCurator でリサーチデータからトピックを選定
2. SegmentGenerator で順次セグメントを生成（intro → deep_dive × N → conclusion）
3. すべてのセグメントを統合して最終的な Script オブジェクトを返す

文脈の連続性は各セグメントの context_summary を次セグメントに渡すことで維持する。
"""
import asyncio
import logging
import time
from typing import Optional, Callable, TYPE_CHECKING

from rich.console import Console

from core.interfaces.script_orchestrator import IScriptOrchestrator
from core.models import AppConfig, Script, LLMUsage
from core.models.curation import CuratedTopic, CurationResult, ScriptSegment
from core.models.script import DialogueTurn, TurnType
from core.models.execution_context import ExecutionContext
from core.models.show_plan import ShowPlan
from core.models.fact_sheet import FactSheet
from services.script_generation.topic_curator import TopicCurator
from services.script_generation.show_runner import ShowRunner
from services.script_generation.fact_extractor import FactExtractor
from services.script_generation.segment_generator import SegmentGenerator
from services.script_generation.metadata_generator import MetadataGenerator
from services.script_generation.adapters.factory import LLMAdapterFactory

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult

logger = logging.getLogger(__name__)
console = Console()


class ScriptOrchestrator(IScriptOrchestrator):
    """Hierarchical Agentic Workflow による長尺台本生成オーケストレーター

    処理フロー:
      Step 1 (Curator):    リサーチデータ → CuratedTopic × N
      Step 2 (Segments):   intro + deep_dive×N + conclusion の順次生成
      Step 3 (Integrate):  全 DialogueTurn を統合 → Script
    """

    def __init__(self, context: ExecutionContext):
        """Initialize ScriptOrchestrator with execution context
        
        Args:
            context: Execution context containing provider and configuration
        """
        super().__init__(context.config)
        self._context = context
        self.orch_cfg = context.config.yaml.script_generator.orchestrator
        
        # Create LLM ports for each component
        # Curator uses lightweight model
        curator_model = self.orch_cfg.curator_model
        self._curator_port = LLMAdapterFactory.create(
            context.config,
            context.provider,
            model_override=curator_model
        )
        
        # Segment generator uses main model
        segment_model = self.orch_cfg.segment_model or None
        self._segment_port = LLMAdapterFactory.create(
            context.config,
            context.provider,
            model_override=segment_model
        )
        
        # Metadata generator uses lightweight model
        self._metadata_port = LLMAdapterFactory.create(
            context.config,
            context.provider,
            model_override=curator_model
        )
        
        # Initialize components with LLM ports
        self.curator = TopicCurator(self._curator_port, context.config)

        # Phase 3: ShowRunner (backward compatible - enabled via config flag)
        # Uses its own LLM port so an independent model can be configured; falls back
        # to curator_model when show_runner.model is empty.
        sr_cfg = getattr(self.orch_cfg, "show_runner", None)
        self._show_runner_enabled = bool(getattr(sr_cfg, "enabled", False))
        show_runner_model = (getattr(sr_cfg, "model", "") or "").strip() or curator_model
        self._show_runner_port = LLMAdapterFactory.create(
            context.config,
            context.provider,
            model_override=show_runner_model,
        )
        self.show_runner = ShowRunner(self._show_runner_port, context.config)

        # Phase 4: FactExtractor (backward compatible - enabled via config flag)
        # Runs BEFORE Curator to provide structured fact sheet as judgment material.
        fe_cfg = getattr(self.orch_cfg, "fact_extractor", None)
        self._fact_extractor_enabled = bool(getattr(fe_cfg, "enabled", False))
        fact_extractor_model = (getattr(fe_cfg, "model", "") or "").strip() or curator_model
        self._fact_extractor_port = LLMAdapterFactory.create(
            context.config,
            context.provider,
            model_override=fact_extractor_model,
        )
        self.fact_extractor = FactExtractor(self._fact_extractor_port, context.config)

        # Pass session_dir to SegmentGenerator for markdown script saving
        markdown_output_dir = getattr(context, 'session_dir', None)
        self.generator = SegmentGenerator(self._segment_port, context.config, markdown_output_dir=markdown_output_dir)
        
        self.metadata_gen = MetadataGenerator(self._metadata_port, context.config)

        # 累積 LLM 使用量（プロバイダー別 + 全体集計）
        self._usage_by_provider: dict[str, LLMUsage] = {}  # プロバイダー別の詳細
        self._total_input_tokens = 0   # 全プロバイダー合計（後方互換性のため保持）
        self._total_output_tokens = 0  # 全プロバイダー合計（後方互換性のため保持）
        self._total_requests = 0       # 全プロバイダー合計（後方互換性のため保持）
        
        # Generated segments for video rendering pipeline
        self.segments: list[ScriptSegment] = []

    async def generate_script(
        self,
        theme: str,
        research_data: "ResearchResult",
        avoid_topics: Optional[str] = None,
        excluded_topics: Optional[str] = None,
        progress_callback=None,
        preset_curation: Optional["CurationResult"] = None,
        preset_show_plan: Optional["ShowPlan"] = None,
        preset_fact_sheet: Optional["FactSheet"] = None,
    ) -> Script:
        """テーマとリサーチデータから長尺台本を生成する

        Args:
            theme: 動画のテーマ
            research_data: リサーチ結果
            avoid_topics: 避けてほしい話題（Negative Prompt）
            excluded_topics: 第2部モード用、第1部コンテキスト（現バージョンでは未使用）
            progress_callback: 進捗報告オブジェクト（.log() / .progress() メソッドを持つ）
            preset_curation: 事前に用意された CurationResult（HITL で人間が編集済みなど）。
                             渡された場合は Step 1 の Curator 実行をスキップして直接使用する。
            preset_show_plan: 事前に用意された ShowPlan（Phase 3、HITL で人間が編集済みなど）。
                              渡された場合は Step 1.5 の ShowRunner 実行をスキップ。
                              None かつ show_runner.enabled=True の場合のみ ShowRunner を走らせる。
            preset_fact_sheet: 事前に用意された FactSheet（Phase 4、HITL ないし前回実行のキャッシュ）。
                               渡された場合は Step 0.5 の FactExtractor 実行をスキップ。
                               None かつ fact_extractor.enabled=True の場合のみ FactExtractor を走らせる。

        Returns:
            Script: 統合された台本オブジェクト
        """
        start_time = time.time()
        log = self._make_log(progress_callback)

        log(f"\n[bold cyan]== ScriptOrchestrator: 長尺台本生成開始 ({self._context.provider}) ==[/bold cyan]")
        log(f"  テーマ: {theme}")
        log(f"  リサーチデータ: {len(research_data.content)}文字")

        self._reset_usage()

        # --------------------------------------------------------
        # Step 0.5: Research 事実抽出（FactExtractor、Phase 4 施策③）
        # 有効化条件:
        #   - preset_fact_sheet が渡されていれば即採用
        #   - それ以外で fact_extractor.enabled=True かつ Curator を実際に走らせる場合のみ実行
        #   - preset_curation が提供される（Curator スキップ）場合は FactExtractor も不要
        # 失敗時は警告ログのみ出して fact_sheet=None で継続（後方互換）
        # --------------------------------------------------------
        fact_sheet: Optional[FactSheet] = None
        curator_will_run = not (preset_curation is not None and preset_curation.topics)
        if preset_fact_sheet is not None:
            log("\n[cyan]--- Step 0.5/3: 事実抽出（プリセット使用、FactExtractor スキップ） ---[/cyan]")
            fact_sheet = preset_fact_sheet
            log(f"  [green]✓ プリセット FactSheet を使用 (facts={len(fact_sheet.facts)})[/green]")
        elif self._fact_extractor_enabled and curator_will_run:
            log("\n[cyan]--- Step 0.5/3: 事実抽出（FactExtractor） ---[/cyan]")
            if progress_callback:
                progress_callback.progress(0.49, "📋 リサーチから事実を抽出中...")
            try:
                fact_sheet = await self.fact_extractor.extract_facts(
                    theme=theme,
                    research_data=research_data,
                    progress_log=log,
                )
                self._accumulate_usage(self.fact_extractor.last_usage)
            except Exception as e:
                # Backward compat: if FactExtractor fails, fall through to legacy flow
                log(f"[yellow]⚠ FactExtractor 失敗（fact_sheet=None で継続）: {e}[/yellow]")
                logger.warning(f"FactExtractor.extract_facts failed; proceeding without FactSheet: {e}")
                fact_sheet = None
        else:
            if not curator_will_run:
                log("[dim]  (preset_curation 指定のため FactExtractor は不要)[/dim]")
            else:
                log("[dim]  (FactExtractor は無効。従来フローで Curator を実行)[/dim]")

        # --------------------------------------------------------
        # Step 1: トピックキュレーション（preset_curation があればスキップ）
        # --------------------------------------------------------
        if preset_curation is not None and preset_curation.topics:
            # HITL で人間が編集済みのトピックを使う
            log("\n[cyan]--- Step 1/3: トピックキュレーション（プリセット使用、Curator スキップ） ---[/cyan]")
            if progress_callback:
                progress_callback.progress(0.50, "🔍 人間編集済みトピックを使用...")
            curation_result = preset_curation
            log(f"  [green]✓ プリセット {len(curation_result.topics)} トピックを使用[/green]")
            for i, topic in enumerate(curation_result.topics, 1):
                log(f"    {i}. {topic.title} (推定{topic.estimated_turns}ターン, tone={topic.tone})")
        else:
            log("\n[cyan]--- Step 1/3: トピックキュレーション ---[/cyan]")
            if progress_callback:
                progress_callback.progress(0.50, "🔍 面白いトピックを選定中...")

            # PR-H: TopicCurator 失敗時のフェイルオープン。
            # 想定される失敗:
            #   - pydantic.ValidationError: CurationResult.topics 非空契約違反 (PR-B)。
            #     qwen3:8b 等の小型モデルが空 topics を返した場合に発生
            #   - RuntimeError: finish_reason=length (PR-D) など
            #   - その他 LLM 呼び出しエラー / JSON parse 失敗
            # PR-B の validator 自体は正しい（壊れた preset_curation を早期検知する用途）が、
            # Curator 実行失敗での raise は orchestrator まで伝播し、PR-H 以前は
            # パイプライン全体がクラッシュしていた。PR-H ではフォールバックトピック 1 件で
            # 番組生成を完走させ、運用者が processing_log.txt から失敗を後追いできるようにする。
            try:
                curation_result = await self.curate_topics(
                    research_data,
                    target_count=self.orch_cfg.max_topics,
                    progress_log=log,
                    fact_sheet=fact_sheet,
                )
                self._accumulate_usage(self.curator.last_usage)
            except Exception as e:
                # last_usage は失敗時 None or 部分的な値の可能性。安全のため accumulate スキップ。
                # 詳細は _build_fallback_curation_for_failure の docstring 参照。
                curation_result = self._build_fallback_curation_for_failure(e, log)

        topic_titles = [t.title for t in curation_result.topics]
        log(f"  選定トピック: {', '.join(topic_titles)}")

        # --------------------------------------------------------
        # Step 1.5: 番組構成プランニング（ShowRunner、Phase 3 施策④）
        # 有効化条件:
        #   - preset_show_plan が渡されていれば即採用
        #   - それ以外で show_runner.enabled=True ならこのタイミングで走らせる
        #   - それ以外（既定）は show_plan=None で従来動作
        # 失敗時は警告ログのみ出して show_plan=None で継続（後方互換）
        # --------------------------------------------------------
        show_plan: Optional[ShowPlan] = None
        if preset_show_plan is not None:
            log("\n[cyan]--- Step 1.5/3: 番組構成プランニング（プリセット使用、ShowRunner スキップ） ---[/cyan]")
            show_plan = preset_show_plan
            log(f"  [green]✓ プリセット ShowPlan を使用 (bridges={len(show_plan.topic_bridges)})[/green]")
        elif self._show_runner_enabled and curation_result.topics:
            log("\n[cyan]--- Step 1.5/3: 番組構成プランニング（ShowRunner） ---[/cyan]")
            if progress_callback:
                progress_callback.progress(0.51, "🎬 番組構成を設計中...")
            try:
                show_plan = await self.show_runner.plan_show(
                    theme=theme,
                    curation_result=curation_result,
                    progress_log=log,
                )
                self._accumulate_usage(self.show_runner.last_usage)
            except Exception as e:
                # Backward compat: if ShowRunner fails, fall through to legacy flow
                log(f"[yellow]⚠ ShowRunner 失敗（従来フローで継続）: {e}[/yellow]")
                logger.warning(f"ShowRunner.plan_show failed; proceeding without ShowPlan: {e}")
                show_plan = None
        else:
            # Backward compat: ShowRunner disabled
            log("[dim]  (ShowRunner は無効。従来フローでセグメント生成)[/dim]")

        # --------------------------------------------------------
        # Step 2: セグメント順次生成
        # --------------------------------------------------------
        total_segments = 1 + len(curation_result.topics) + 1  # intro + N + conclusion
        all_segments: list[ScriptSegment] = []
        self.segments = []  # Reset segments for this generation
        context = ""

        # --- 2a: 導入セグメント ---
        seg_num = 1
        log(f"\n[cyan]--- Step 2/{total_segments + 1}: 導入セグメント生成 ---[/cyan]")
        if progress_callback:
            pct = 0.52 + (seg_num / total_segments) * 0.12
            progress_callback.progress(pct, "📝 導入部を生成中...")

        # 施策②: 筆頭トピックの最重要ファクトを冒頭フック用に抽出
        # Defensive: topics may be empty or key_facts may be missing/empty
        hook_fact: Optional[str] = None
        if curation_result.topics:
            top_topic = curation_result.topics[0]
            top_facts = getattr(top_topic, "key_facts", None) or []
            if top_facts and isinstance(top_facts[0], str) and top_facts[0].strip():
                hook_fact = top_facts[0].strip()

        intro = await self._generate_with_retry(
            lambda: self.generator.generate_intro(
                theme=theme,
                topic_titles=topic_titles,
                context=context,
                progress_log=log,
                hook_fact=hook_fact,
                show_plan_hint=self._build_intro_hint(show_plan),
            ),
            label="導入セグメント",
            log=log,
        )
        self._accumulate_usage(self.generator.last_usage)
        all_segments.append(intro)
        context = intro.context_summary
        seg_num += 1

        # --- 2b: 深掘りセグメント（トピックごと） ---
        for idx, topic in enumerate(curation_result.topics, 1):
            log(f"\n[cyan]--- Step {seg_num + 1}/{total_segments + 1}: 深掘りセグメント{idx} ---[/cyan]")
            if progress_callback:
                pct = 0.52 + (seg_num / total_segments) * 0.12
                progress_callback.progress(pct, f"📝 深掘り「{topic.title[:20]}」生成中...")

            deep_dive_hint = self._build_deep_dive_hint(show_plan, topic_index=idx - 1)
            deep_dive = await self._generate_with_retry(
                lambda t=topic, i=idx, h=deep_dive_hint: self.generator.generate_deep_dive(
                    topic=t,
                    segment_index=i,
                    context=context,
                    progress_log=log,
                    show_plan_hint=h,
                ),
                label=f"深掘りセグメント{idx}「{topic.title}」",
                log=log,
            )
            self._accumulate_usage(self.generator.last_usage)
            all_segments.append(deep_dive)
            context = deep_dive.context_summary
            seg_num += 1

        # --- 2c: まとめセグメント ---
        log(f"\n[cyan]--- Step {seg_num + 1}/{total_segments + 1}: まとめセグメント生成 ---[/cyan]")
        if progress_callback:
            progress_callback.progress(0.63, "📝 まとめを生成中...")

        # 施策②: 全トピックの key_facts と各セグメントの振り返りを総括素材として集約
        # Defensive: topics/key_facts may be missing; guard with getattr and isinstance
        all_key_facts: list[str] = []
        for t in curation_result.topics or []:
            facts = getattr(t, "key_facts", None) or []
            for f in facts:
                if isinstance(f, str) and f.strip():
                    all_key_facts.append(f.strip())

        # Build segments_recap from each previously generated segment's context_summary.
        # We tag each line with the topic title so the LLM can ground its recap on concrete references.
        recap_lines: list[str] = []
        # all_segments at this point: [intro, deep_dive_1, ..., deep_dive_N]
        for seg in all_segments:
            summary = (getattr(seg, "context_summary", "") or "").strip()
            if not summary:
                continue
            # Label by topic title when available (deep_dive), else by segment_type
            label = getattr(seg, "topic_title", None) or getattr(seg, "segment_type", "segment")
            recap_lines.append(f"- [{label}] {summary}")
        segments_recap = "\n".join(recap_lines) if recap_lines else ""

        conclusion = await self._generate_with_retry(
            lambda: self.generator.generate_conclusion(
                theme=theme,
                topic_titles=topic_titles,
                context=context,
                progress_log=log,
                all_key_facts=all_key_facts or None,
                segments_recap=segments_recap or None,
                show_plan_hint=self._build_conclusion_hint(
                    show_plan, topic_count=len(curation_result.topics)
                ),
            ),
            label="まとめセグメント",
            log=log,
        )
        self._accumulate_usage(self.generator.last_usage)
        all_segments.append(conclusion)

        # --------------------------------------------------------
        # Step 3: 統合
        # --------------------------------------------------------
        log(f"\n[cyan]--- Step 3/4: セグメント統合 ---[/cyan]")
        self.segments = all_segments  # Store segments for video rendering
        script = self._integrate_segments(theme, all_segments)

        total_turns = len(script.sections)
        log(f"[green]✓ セグメント統合完了: {total_turns}ターン[/green]")

        # --------------------------------------------------------
        # Step 4: メタデータ生成（後処理）
        # --------------------------------------------------------
        log(f"\n[cyan]--- Step 4/4: メタデータ生成 ---[/cyan]")
        if progress_callback:
            progress_callback.progress(0.65, "📝 メタデータ（タイトル・概要欄）を生成中...")

        try:
            script = await self.metadata_gen.generate(
                theme=theme,
                script=script,
                research_data=research_data,
                progress_log=log,
            )
            self._accumulate_usage(self.metadata_gen.last_usage)
        except Exception as e:
            logger.warning(f"MetadataGenerator failed (non-fatal): {e}")
            log(f"[yellow]⚠ メタデータ生成エラー（スキップ）: {e}[/yellow]")

        elapsed = time.time() - start_time
        log(f"[bold green]✓ ScriptOrchestrator 完了: {total_turns}ターン ({elapsed:.1f}秒)[/bold green]")
        log(f"  API呼び出し: {self._total_requests}回 / "
            f"トークン合計: 入力{self._total_input_tokens:,} / 出力{self._total_output_tokens:,}")

        if progress_callback:
            progress_callback.progress(0.68, f"✅ 台本・メタデータ生成完了（{total_turns}ターン）")

        return script

    async def curate_topics(
        self,
        research_data: "ResearchResult",
        target_count: int = 3,
        progress_log=None,
        fact_sheet: Optional["FactSheet"] = None,
    ) -> CurationResult:
        """リサーチデータからトピックを選定（IScriptOrchestrator の実装）

        Args:
            fact_sheet: Phase 4 施策③、Curator に判断材料として差し込む構造化ファクト。
                        None の場合は従来通り動作（後方互換）。
        """
        return await self.curator.curate_topics(
            research_data=research_data,
            target_count=target_count,
            progress_log=progress_log,
            fact_sheet=fact_sheet,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_fallback_curation_for_failure(
        self, e: Exception, log: Callable
    ) -> CurationResult:
        """PR-H: TopicCurator 失敗時のフォールバック CurationResult 構築。

        想定される失敗:
          - `pydantic.ValidationError`: `CurationResult.topics` 非空契約違反 (PR-B)。
            qwen3:8b 等の小型モデルが空 topics を返した場合に発生。
          - `RuntimeError`: `finish_reason=length` (PR-D) など。
          - その他 LLM 呼び出しエラー / JSON parse 失敗。

        PR-B の validator 自体は正しい（壊れた preset_curation を早期検知する用途）が、
        Curator 実行失敗での raise は orchestrator まで伝播し、PR-H 以前は
        パイプライン全体がクラッシュしていた。本メソッドは番組完走のためのプレースホルダ
        topic 1 件を持つ `CurationResult` を返し、運用者が processing_log.txt から失敗を
        後追いできるよう logger.error と rich console 出力（cb.log 経由）の両方に記録する。

        Args:
            e: Curator が raise した例外
            log: rich console 出力用 callback（PR-C の LogFileWriter.write 経由で
                 processing_log.txt に届く）

        Returns:
            CurationResult: フォールバックトピック 1 件を持つ valid な CurationResult。
                            PR-B の topics 非空 validator を通過する。
        """
        error_type = type(e).__name__
        msg = (
            f"TopicCurator failed; falling back to a single placeholder topic so the "
            f"pipeline completes. error_type={error_type}, error={e}"
        )
        # PR-C/F 連携: logger.error は _SessionLogFileHandler 経由で processing_log.txt に
        # `>>> [ERROR] [services.script_generation.orchestrator] ...` として残る
        logger.error(msg, exc_info=True)
        log(f"[red]✗ TopicCurator 失敗（フォールバックトピックで継続）: {error_type}: {e}[/red]")

        # フォールバック topic: 番組完走のためのプレースホルダ。
        # 視聴者から見ても「失敗時のフォールバック」と分かる文言にする。
        # 下流の SegmentGenerator は通常通りこの topic で 1 つの deep_dive を生成する。
        fallback_topic = CuratedTopic(
            title="（自動生成失敗:詳細は processing_log.txt 参照）",
            content=(
                "TopicCurator がトピック選定に失敗したため、フォールバックトピックで"
                "番組を継続しています。リサーチ内容そのものを概観する形で進行します。"
            ),
            priority=1,
            estimated_turns=10,
            tone="解説",
            key_facts=[],
            selection_reason=(
                f"Curator 失敗時のフォールバック (error_type={error_type})"
            ),
        )
        return CurationResult(
            topics=[fallback_topic],
            curator_reasoning=(
                f"TopicCurator failed and a fallback topic was used. "
                f"error_type={error_type}, error={e}"
            ),
        )

    def _build_intro_hint(self, show_plan: Optional[ShowPlan]) -> Optional[str]:
        """ShowPlan から導入セグメント用のヒント文字列を生成

        Returns:
            ヒント文字列。show_plan が None の場合や内容が空の場合は None
            （SegmentGenerator 側で無視される）。
        """
        if show_plan is None:
            return None
        parts: list[str] = []
        if show_plan.overall_arc:
            parts.append(f"【番組全体アーク】{show_plan.overall_arc}")
        if show_plan.intro_hook_strategy:
            parts.append(f"【導入フック戦略】{show_plan.intro_hook_strategy}")
        # intro → topic[0] のブリッジ
        bridge = show_plan.get_bridge_out_of(-1)
        if bridge and bridge.transition_hint:
            parts.append(f"【導入→トピック1への接続】{bridge.transition_hint}")
        if show_plan.overall_tone:
            parts.append(f"【トーン配分】{show_plan.overall_tone}")
        return "\n".join(parts) if parts else None

    def _build_deep_dive_hint(
        self, show_plan: Optional[ShowPlan], topic_index: int
    ) -> Optional[str]:
        """ShowPlan から深掘りセグメント用のヒント文字列を生成

        Args:
            show_plan: 番組構成プラン（None可）
            topic_index: 対象トピックの 0-based インデックス

        Returns:
            ヒント文字列 or None
        """
        if show_plan is None:
            return None
        parts: list[str] = []
        # このトピックに"入る"ブリッジ（前のセグメントからの接続ヒント）
        bridge_in = show_plan.get_bridge_into(topic_index)
        if bridge_in and bridge_in.transition_hint:
            src_label = "導入" if bridge_in.from_topic_index == -1 else f"前の深掘り({bridge_in.from_topic_index})"
            parts.append(f"【{src_label}からの接続意図】{bridge_in.transition_hint}")
        # このトピックから"出る"ブリッジ（次への布石として意識させる）
        bridge_out = show_plan.get_bridge_out_of(topic_index)
        if bridge_out and bridge_out.transition_hint:
            dst_label = "まとめ" if bridge_out.to_topic_index == -1 else f"次の深掘り({bridge_out.to_topic_index})"
            parts.append(f"【{dst_label}への橋渡し意図（セグメント末尾で布石を置く）】{bridge_out.transition_hint}")
        if show_plan.overall_tone:
            parts.append(f"【番組全体のトーン配分】{show_plan.overall_tone}")
        return "\n".join(parts) if parts else None

    def _build_conclusion_hint(
        self, show_plan: Optional[ShowPlan], topic_count: int
    ) -> Optional[str]:
        """ShowPlan からまとめセグメント用のヒント文字列を生成

        Args:
            show_plan: 番組構成プラン（None可）
            topic_count: 深掘りトピック総数（最後のトピックインデックスを特定するため）

        Returns:
            ヒント文字列 or None
        """
        if show_plan is None:
            return None
        parts: list[str] = []
        # 最終深掘り → まとめ のブリッジ
        if topic_count > 0:
            bridge = show_plan.get_bridge_into(-1)
            if bridge and bridge.transition_hint:
                parts.append(f"【最終深掘りからの接続意図】{bridge.transition_hint}")
        if show_plan.conclusion_strategy:
            parts.append(f"【締め戦略】{show_plan.conclusion_strategy}")
        if show_plan.overall_arc:
            parts.append(f"【番組全体アーク（着地点の参考）】{show_plan.overall_arc}")
        if show_plan.overall_tone:
            parts.append(f"【トーン配分】{show_plan.overall_tone}")
        return "\n".join(parts) if parts else None

    def _integrate_segments(self, theme: str, segments: list[ScriptSegment]) -> Script:
        """全セグメントの turns を結合して Script オブジェクトを生成"""
        all_turns: list[DialogueTurn] = []

        for seg in segments:
            for turn_dict in seg.turns:
                try:
                    # speaker_id → speaker 後方互換変換
                    if "speaker_id" in turn_dict and "speaker" not in turn_dict:
                        sid = turn_dict.pop("speaker_id")
                        turn_dict["speaker"] = "A" if sid == "main" else "B"

                    # turn_type が指定されていない場合はデフォルト
                    if "turn_type" not in turn_dict:
                        turn_dict["turn_type"] = TurnType.DIALOGUE

                    turn = DialogueTurn(**turn_dict)
                    all_turns.append(turn)
                except Exception as e:
                    logger.warning(f"DialogueTurn 変換スキップ: {e} / data={turn_dict}")
                    continue

        if len(all_turns) < 10:
            logger.warning(f"統合後のターン数が少なすぎます: {len(all_turns)}")

        return Script(
            title="",           # 後工程（メタデータ生成）で設定
            theme=theme,
            sections=all_turns,
            thumbnail_title="",
            description="",
            hashtags=[],
            references=[],
        )

    async def _generate_with_retry(
        self,
        generate_fn: Callable,
        label: str,
        log: Callable,
        max_retries: int = 2,
    ) -> ScriptSegment:
        """セグメント生成を最大 max_retries 回リトライする"""
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await generate_fn()
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    log(f"[yellow]⚠ {label} 失敗 ({attempt + 1}/{max_retries})。{wait}秒後にリトライ: {e}[/yellow]")
                    await asyncio.sleep(wait)
                else:
                    log(f"[red]✗ {label} リトライ上限到達: {e}[/red]")
        raise last_exc

    def _accumulate_usage(self, usage: Optional[LLMUsage]) -> None:
        """API使用量を累積（プロバイダー別に安全に集計）
        
        異なるプロバイダーのLLMUsageを直接加算するとValueErrorが発生するため、
        プロバイダーごとに分離して累積する。
        
        Args:
            usage: 追加するLLM使用量（Noneの場合はスキップ）
        """
        if not usage:
            return
        
        provider = usage.provider
        
        # プロバイダー別の累積
        if provider not in self._usage_by_provider:
            # 新しいプロバイダーの場合は初期化
            self._usage_by_provider[provider] = LLMUsage(
                provider=provider,
                model_name=usage.model_name,
                input_tokens=0,
                output_tokens=0,
                request_count=0,
            )
        
        # 同一プロバイダー内での加算（LLMUsage.__add__が安全に動作）
        self._usage_by_provider[provider] = self._usage_by_provider[provider] + usage
        
        # 全体集計の更新（後方互換性のため）
        self._total_input_tokens += usage.input_tokens
        self._total_output_tokens += usage.output_tokens
        self._total_requests += usage.request_count
        
        logger.debug(
            f"[Orchestrator] Accumulated usage: {provider} "
            f"(+{usage.input_tokens} in, +{usage.output_tokens} out, +{usage.request_count} req)"
        )

    def _reset_usage(self) -> None:
        """使用量カウンターをリセット"""
        self._usage_by_provider.clear()
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_requests = 0

    def get_total_usage(self) -> LLMUsage:
        """累積 LLM 使用量を返す（後方互換性のため単一LLMUsageを返す）
        
        注意: マルチプロバイダー使用時は情報が失われます。
        詳細な内訳が必要な場合は get_usage_by_provider() を使用してください。
        
        Returns:
            LLMUsage: 全プロバイダーの合計使用量（providerは最初に使用されたもの）
        """
        # プロバイダーが1つだけの場合はそれを返す
        if len(self._usage_by_provider) == 1:
            return list(self._usage_by_provider.values())[0]
        
        # 複数プロバイダーの場合は合計値を返す（providerは最初のもの）
        first_provider = list(self._usage_by_provider.keys())[0] if self._usage_by_provider else "gemini"
        
        return LLMUsage(
            provider=first_provider,
            model_name="orchestrator",
            input_tokens=self._total_input_tokens,
            output_tokens=self._total_output_tokens,
            request_count=self._total_requests,
        )

    def get_usage_by_provider(self) -> dict[str, LLMUsage]:
        """プロバイダー別のLLM使用量を返す（詳細版）
        
        Returns:
            dict[str, LLMUsage]: プロバイダー名をキーとした使用量の辞書
        """
        return self._usage_by_provider.copy()

    @staticmethod
    def _make_log(progress_callback) -> Callable:
        """progress_callback または console.print を log 関数として返す"""
        if progress_callback and hasattr(progress_callback, "log"):
            return progress_callback.log
        return lambda msg: console.print(msg)
