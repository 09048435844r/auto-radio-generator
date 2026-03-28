"""ScriptOrchestrator - 台本生成の全体統括エージェント

Hierarchical Agentic Workflow の司令塔。
1. TopicCurator でリサーチデータからトピックを選定
2. SegmentGenerator で順次セグメントを生成（intro → deep_dive × N → conclusion）
3. すべてのセグメントを統合して最終的な Script オブジェクトを返す

文脈の連続性は各セグメントの context_summary を次セグメントに渡すことで維持する。
"""
import logging
import time
from typing import Optional, Callable, TYPE_CHECKING

from rich.console import Console

from core.interfaces.script_orchestrator import IScriptOrchestrator
from core.models import AppConfig, Script, LLMUsage
from core.models.curation import CurationResult, ScriptSegment
from core.models.script import DialogueTurn, TurnType
from services.script_generation.topic_curator import TopicCurator
from services.script_generation.segment_generator import SegmentGenerator
from services.script_generation.metadata_generator import MetadataGenerator

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

    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.curator = TopicCurator(config)
        self.generator = SegmentGenerator(config)
        self.metadata_gen = MetadataGenerator(config)
        self.orch_cfg = config.yaml.script_generator.orchestrator

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
    ) -> Script:
        """テーマとリサーチデータから長尺台本を生成する

        Args:
            theme: 動画のテーマ
            research_data: リサーチ結果
            avoid_topics: 避けてほしい話題（Negative Prompt）
            excluded_topics: 第2部モード用、第1部コンテキスト（現バージョンでは未使用）
            progress_callback: 進捗報告オブジェクト（.log() / .progress() メソッドを持つ）

        Returns:
            Script: 統合された台本オブジェクト
        """
        start_time = time.time()
        log = self._make_log(progress_callback)

        log("\n[bold cyan]== ScriptOrchestrator: 長尺台本生成開始 ==[/bold cyan]")
        log(f"  テーマ: {theme}")
        log(f"  リサーチデータ: {len(research_data.content)}文字")

        self._reset_usage()

        # --------------------------------------------------------
        # Step 1: トピックキュレーション
        # --------------------------------------------------------
        log("\n[cyan]--- Step 1/3: トピックキュレーション ---[/cyan]")
        if progress_callback:
            progress_callback.progress(0.50, "🔍 面白いトピックを選定中...")

        curation_result = await self.curate_topics(
            research_data,
            target_count=self.orch_cfg.max_topics,
            progress_log=log,
        )
        self._accumulate_usage(self.curator.last_usage)

        topic_titles = [t.title for t in curation_result.topics]
        log(f"  選定トピック: {', '.join(topic_titles)}")

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

        intro = await self._generate_with_retry(
            lambda: self.generator.generate_intro(
                theme=theme,
                topic_titles=topic_titles,
                context=context,
                progress_log=log,
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

            deep_dive = await self._generate_with_retry(
                lambda t=topic, i=idx: self.generator.generate_deep_dive(
                    topic=t,
                    segment_index=i,
                    context=context,
                    progress_log=log,
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

        conclusion = await self._generate_with_retry(
            lambda: self.generator.generate_conclusion(
                theme=theme,
                topic_titles=topic_titles,
                context=context,
                progress_log=log,
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
    ) -> CurationResult:
        """リサーチデータからトピックを選定（IScriptOrchestrator の実装）"""
        return await self.curator.curate_topics(
            research_data=research_data,
            target_count=target_count,
            progress_log=progress_log,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
                    time.sleep(wait)
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
