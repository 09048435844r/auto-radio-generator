"""SegmentGenerator - 台本の1セグメントを生成するエージェント

Hierarchical Agentic Workflow の Step 2。
TopicCuratorが選定したトピックを受け取り、セグメントタイプ
（intro / deep_dive / conclusion）に応じた台本を生成する。
前セグメントの文脈要約を受け取り、会話の連続性を維持する。

2段階生成モード:
- Phase 1: Markdown形式でクリエイティブに台本を生成（temperature: 0.85）
- Phase 2: Phase 1の出力をJSON形式に変換（temperature: 0.3）
"""
import asyncio
import json
import logging
import re
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

        # 2段階生成モードの設定
        self.two_phase_enabled = orch_cfg.two_phase_generation
        
        # デバッグ出力（コンソール + ログ）
        init_msg = f"SegmentGenerator initialized: two_phase_enabled={self.two_phase_enabled}, model={self.segment_model}"
        logger.info(init_msg)
        console.print(f"[yellow]{init_msg}[/yellow]")

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

        user_prompt = self._build_intro_user_prompt(theme, topic_titles, context)

        if self.two_phase_enabled:
            # 2段階生成モード
            log(f"[dim]  Phase 1: クリエイティブ生成中...[/dim]")
            markdown_script, usage1 = await self._generate_creative_markdown(
                segment_type="intro",
                user_prompt=user_prompt,
                min_turns=self.intro_cfg.min_turns,
                max_turns=self.intro_cfg.max_turns,
                context=context,
            )
            
            log(f"[dim]  Phase 2: JSON構造化中...[/dim]")
            response_text, usage2 = await self._convert_markdown_to_json_with_fallback(
                markdown_script=markdown_script,
                segment_type="intro",
            )
            
            # Usage合算
            self.last_usage = self._merge_usage(usage1, usage2)
        else:
            # 従来の1段階生成モード
            system_prompt = self.prompt_manager.get_prompt("orchestrator", "segment_intro").format(
                min_turns=self.intro_cfg.min_turns,
                max_turns=self.intro_cfg.max_turns,
            )
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
        user_prompt = self._build_deep_dive_user_prompt(topic)

        if self.two_phase_enabled:
            # 2段階生成モード
            log(f"[dim]  Phase 1: クリエイティブ生成中...[/dim]")
            markdown_script, usage1 = await self._generate_creative_markdown(
                segment_type="deep_dive",
                user_prompt=user_prompt,
                min_turns=self.deep_dive_cfg.min_turns,
                max_turns=self.deep_dive_cfg.max_turns,
                context=context,
            )
            
            log(f"[dim]  Phase 2: JSON構造化中...[/dim]")
            response_text, usage2 = await self._convert_markdown_to_json_with_fallback(
                markdown_script=markdown_script,
                segment_type="deep_dive",
            )
            
            # Usage合算
            self.last_usage = self._merge_usage(usage1, usage2)
        else:
            # 従来の1段階生成モード
            section_marker = f"main_{segment_index}" if segment_index > 1 else "main"
            system_prompt = self.prompt_manager.get_prompt("orchestrator", "segment_deep_dive").format(
                context=context or "（前のセグメントはありません。これが番組の最初です）",
                min_turns=self.deep_dive_cfg.min_turns,
                max_turns=self.deep_dive_cfg.max_turns,
                segment_id=segment_id,
                topic_title=topic.title,
                section_marker=section_marker,
            )
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

        user_prompt = self._build_conclusion_user_prompt(theme, topic_titles)

        if self.two_phase_enabled:
            # 2段階生成モード
            log(f"[dim]  Phase 1: クリエイティブ生成中...[/dim]")
            markdown_script, usage1 = await self._generate_creative_markdown(
                segment_type="conclusion",
                user_prompt=user_prompt,
                min_turns=self.conclusion_cfg.min_turns,
                max_turns=self.conclusion_cfg.max_turns,
                context=context,
            )
            
            log(f"[dim]  Phase 2: JSON構造化中...[/dim]")
            response_text, usage2 = await self._convert_markdown_to_json_with_fallback(
                markdown_script=markdown_script,
                segment_type="conclusion",
            )
            
            # Usage合算
            self.last_usage = self._merge_usage(usage1, usage2)
        else:
            # 従来の1段階生成モード
            system_prompt = self.prompt_manager.get_prompt("orchestrator", "segment_conclusion").format(
                context=context or "（文脈情報なし）",
                min_turns=self.conclusion_cfg.min_turns,
                max_turns=self.conclusion_cfg.max_turns,
            )
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

    # ------------------------------------------------------------------
    # Two-phase generation methods
    # ------------------------------------------------------------------

    async def _generate_creative_markdown(
        self,
        segment_type: str,
        user_prompt: str,
        min_turns: int,
        max_turns: int,
        context: str = "",
    ) -> tuple[str, LLMUsage]:
        """Phase 1: Markdown形式でクリエイティブに台本を生成
        
        Args:
            segment_type: セグメントタイプ (intro/deep_dive/conclusion)
            user_prompt: ユーザープロンプト
            min_turns: 最小ターン数
            max_turns: 最大ターン数
            context: 前セグメントの文脈要約
        
        Returns:
            tuple[Markdown台本, LLMUsage]
        """
        # Phase 1用のクリエイティブプロンプトを取得
        system_prompt = self.prompt_manager.get_prompt(
            "orchestrator", 
            f"segment_{segment_type}_creative"
        ).format(
            min_turns=min_turns,
            max_turns=max_turns,
            context=context or "（前のセグメントはありません。これが番組の最初です）"
        )
        
        # API呼び出し（JSON形式を要求しない）
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.segment_model,
            max_tokens=4096,  # Phase 1は長めに
            temperature=0.85,  # 創造性重視
            response_format="text"  # JSON不要
        )
        
        console.print(
            f"[dim]  Phase 1 API: provider={self._llm.provider_name}, model={self.segment_model}, "
            f"max_tokens=4096, temperature=0.85[/dim]"
        )
        
        response = await self._llm.generate(request)
        
        logger.debug(
            f"Phase 1 (Creative): provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        
        return response.content, response.usage

    async def _convert_markdown_to_json(
        self,
        markdown_script: str,
        segment_type: str,
    ) -> tuple[str, LLMUsage]:
        """Phase 2: Markdown台本をJSON形式に変換
        
        Args:
            markdown_script: Phase 1で生成されたMarkdown台本
            segment_type: セグメントタイプ
        
        Returns:
            tuple[JSON文字列, LLMUsage]
        """
        system_prompt = self.prompt_manager.get_prompt(
            "orchestrator",
            "markdown_to_json"
        ).format(
            markdown_script=markdown_script,
            segment_type=segment_type
        )
        
        # API呼び出し（構造化に特化）
        request = LLMRequest(
            system_prompt="You are a JSON converter. Convert Markdown dialogue to JSON format.",
            user_prompt=system_prompt,  # プロンプト全体をuser_promptに移動
            model=self.segment_model,
            max_tokens=2048,  # Phase 2は短めでOK
            temperature=0.1,  # 正確性最優先
            response_format="json"
        )
        
        console.print(
            f"[dim]  Phase 2 API: provider={self._llm.provider_name}, model={self.segment_model}, "
            f"max_tokens=2048, temperature=0.1[/dim]"
        )
        
        response = await self._llm.generate(request)
        
        logger.debug(
            f"Phase 2 (JSON): provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        
        return response.content, response.usage

    async def _convert_markdown_to_json_with_fallback(
        self,
        markdown_script: str,
        segment_type: str,
    ) -> tuple[str, LLMUsage]:
        """Phase 2のJSON変換（Direct Regex Bypass対応）
        
        ローカルLLM（Ollama等）の場合、Phase 2のLLM呼び出しをスキップし、
        直接正規表現パーサーでJSON生成を行う。
        
        Rationale for Direct Regex Bypass:
        - ローカルLLMはJSON構造化が不安定で、Phase 2の精度が低い
        - 正規表現パーサーの方が高速かつ確実
        - API呼び出しコストがゼロ（ローカル実行のため時間短縮）
        
        Args:
            markdown_script: Markdown台本
            segment_type: セグメントタイプ
        
        Returns:
            tuple[JSON文字列, LLMUsage]
        """
        # Direct Regex Bypass: ローカルLLMの場合はPhase 2をスキップ
        orch_cfg = self.config.yaml.script_generator.orchestrator
        if self._llm.provider_name.lower() in orch_cfg.LOCAL_LLM_PROVIDERS:
            console.print(
                f"[cyan]⚡ Direct Regex Bypass: Phase 2 LLM呼び出しをスキップ "
                f"(provider={self._llm.provider_name})[/cyan]"
            )
            
            try:
                # 正規表現パーサーで直接JSON生成
                json_text = self._parse_markdown_to_json(markdown_script, segment_type)
                
                # Usageはダミー（Phase 1で既にトークン消費済み、Phase 2はAPI呼び出しなし）
                bypass_usage = LLMUsage(
                    provider=self._llm.provider_name,
                    model_name=self.segment_model,
                    input_tokens=0,  # Phase 2 bypassed: no API call
                    output_tokens=0,  # Phase 2 bypassed: no API call
                    request_count=0,  # Phase 2 bypassed: no API call
                )
                
                console.print(f"[green]✓ 正規表現パーサーでJSON生成完了[/green]")
                return json_text, bypass_usage
                
            except ValueError as e:
                # 正規表現パーサー失敗時のフォールバック
                logger.error(f"Direct Regex Bypass failed: {e}")
                console.print(
                    f"[yellow]⚠️ 正規表現パーサー失敗。Phase 2 LLM呼び出しにフォールバックします[/yellow]"
                )
                # フォールバック: Phase 2のLLM呼び出しを実行
                # （以下の通常フローに続く）
        
        # クラウドLLM（Gemini/GPT等）の場合、または正規表現パーサー失敗時はPhase 2を実行
        try:
            # 通常のJSON変換を試行
            json_text, usage = await self._convert_markdown_to_json(
                markdown_script, segment_type
            )
            
            # パース可能か検証
            json.loads(json_text.strip(), strict=False)
            console.print(f"[green]✓ Phase 2: JSON変換成功[/green]")
            return json_text, usage
            
        except json.JSONDecodeError as e:
            logger.warning(f"Phase 2 JSON変換失敗: {e}")
            console.print(f"[yellow]⚠️ Phase 2失敗。フォールバックパーサーを使用します[/yellow]")
            
            # フォールバック: Markdownを正規表現でパース
            json_text = self._parse_markdown_to_json(markdown_script, segment_type)
            
            # Usageはダミー（フォールバックなのでAPI呼び出しなし）
            fallback_usage = LLMUsage(
                provider=self._llm.provider_name,
                model_name=self.segment_model,
                input_tokens=0,
                output_tokens=0,
                request_count=0,
            )
            
            console.print(f"[green]✓ フォールバックパーサーでJSON生成成功[/green]")
            return json_text, fallback_usage

    def _parse_markdown_to_json(
        self,
        markdown_script: str,
        segment_type: str,
    ) -> str:
        """MarkdownをパースしてJSON文字列を生成（フォールバック）
        
        Args:
            markdown_script: Markdown台本
            segment_type: セグメントタイプ
        
        Returns:
            JSON文字列
        """
        turns = []
        
        # 正規表現で「**話者名**: セリフ」を抽出
        # パターン: **A**: または **B**: で始まり、次の話者または文末まで
        pattern = r'\*\*([AB])\*\*:\s*(.+?)(?=\n\*\*[AB]\*\*:|$)'
        matches = re.findall(pattern, markdown_script, re.DOTALL)
        
        # マッチが0件の場合は明示的にエラーを発生
        if not matches:
            raise ValueError(
                f"Fallback parser failed: No valid speaker patterns found in Markdown.\n"
                f"Expected format: '**A**: text' or '**B**: text'\n"
                f"Markdown preview (first 500 chars): {markdown_script[:500]}"
            )
        
        for speaker, text in matches:
            # セリフのクリーンアップ（連続する空白を1つに正規化）
            cleaned_text = text.strip()
            # 改行や連続空白を単一スペースに正規化
            cleaned_text = ' '.join(cleaned_text.split())
            
            turns.append({
                "speaker": speaker,
                "text": cleaned_text,
                "section": segment_type,
                "chapter_title": None
            })
        
        segment_dict = {
            "segment_id": segment_type,
            "segment_type": segment_type,
            "topic_title": None,
            "turns": turns,
            "context_summary": ""
        }
        
        logger.info(f"Fallback parser extracted {len(turns)} turns from Markdown")
        return json.dumps(segment_dict, ensure_ascii=False, indent=2)

    def _merge_usage(self, usage1: LLMUsage, usage2: LLMUsage) -> LLMUsage:
        """2つのLLMUsageを合算
        
        Args:
            usage1: Phase 1のUsage
            usage2: Phase 2のUsage
        
        Returns:
            合算されたLLMUsage
        """
        return LLMUsage(
            provider=usage1.provider,
            model_name=usage1.model_name,
            input_tokens=usage1.input_tokens + usage2.input_tokens,
            output_tokens=usage1.output_tokens + usage2.output_tokens,
            request_count=usage1.request_count + usage2.request_count,
        )

