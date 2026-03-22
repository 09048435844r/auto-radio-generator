"""SegmentGenerator - 台本の1セグメントを生成するエージェント

Hierarchical Agentic Workflow の Step 2。
TopicCuratorが選定したトピックを受け取り、セグメントタイプ
（intro / deep_dive / conclusion）に応じた台本を生成する。
前セグメントの文脈要約を受け取り、会話の連続性を維持する。
"""
import json
import logging
from typing import Optional, TYPE_CHECKING

from rich.console import Console

from core.models import AppConfig, LLMUsage
from core.models.curation import CuratedTopic, ScriptSegment
from core.prompt_manager import PromptManager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
console = Console()


class SegmentGenerator:
    """1つの台本セグメントを生成するエージェント

    各セグメントは独立したAPI呼び出しで生成されるため、
    max_output_tokens の壁を回避できる。
    セグメントタイプに応じた専用プロンプトを使用する。
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.prompt_manager = PromptManager()

        orch_cfg = config.yaml.script_generator.orchestrator
        gemini_cfg = config.yaml.script_generator.gemini

        # セグメント生成はメインモデルを使用（空の場合は gemini.model を使用）
        self.segment_model = orch_cfg.segment_model or gemini_cfg.model
        self.fallback_model = gemini_cfg.fallback_model

        # セグメント別ターン数設定
        self.intro_cfg = orch_cfg.intro
        self.deep_dive_cfg = orch_cfg.deep_dive
        self.conclusion_cfg = orch_cfg.conclusion

        # Gemini クライアントを初期化
        from google import genai
        from google.genai import types
        self._genai = genai
        self._types = types
        self.client = genai.Client(api_key=config.env.gemini_api_key)

        # セーフティ設定
        self.safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        ]

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

        response_text, usage = self._call_api(system_prompt, user_prompt)
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

        response_text, usage = self._call_api(system_prompt, user_prompt)
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

        response_text, usage = self._call_api(system_prompt, user_prompt)
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

    def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        model_override: Optional[str] = None,
    ) -> tuple[str, LLMUsage]:
        """Gemini APIを呼び出してセグメントを生成"""
        import time

        model_to_use = model_override or self.segment_model

        config_params = {
            "max_output_tokens": 8192,  # 1セグメント分は 8K で十分
            "temperature": 0.85,
            "response_mime_type": "application/json",
            "safety_settings": self.safety_settings,
        }

        console.print(
            f"[dim]SegmentGenerator API: model={model_to_use}, max_tokens={config_params['max_output_tokens']}[/dim]"
        )

        max_retries = 2
        last_exc = None
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=model_to_use,
                    contents=[
                        self._types.Content(
                            role="user",
                            parts=[self._types.Part(text=f"{system_prompt}\n\n{user_prompt}")]
                        )
                    ],
                    config=self._types.GenerateContentConfig(**config_params),
                )
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                error_msg = str(e).lower()
                if (
                    ("disconnected" in error_msg or "timeout" in error_msg or "connection" in error_msg)
                    and attempt < max_retries - 1
                ):
                    wait_time = 2 ** attempt
                    console.print(f"[yellow]接続エラー ({attempt + 1}/{max_retries})。{wait_time}秒後にリトライ...[/yellow]")
                    time.sleep(wait_time)
                    continue
                raise

        if last_exc:
            raise last_exc

        # finish_reason チェック
        if response.candidates:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", "UNKNOWN")
            if finish_reason == "MAX_TOKENS":
                logger.warning(f"SegmentGenerator: MAX_TOKENS に到達。出力が切り詰められた可能性あり (model={model_to_use})")
            elif finish_reason in ("SAFETY", "RECITATION"):
                logger.warning(f"SegmentGenerator: finish_reason={finish_reason}")

        usage = LLMUsage(
            provider="gemini",
            model_name=model_to_use,
            input_tokens=0,
            output_tokens=0,
            request_count=1,
        )
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage.input_tokens = getattr(meta, "prompt_token_count", 0) or 0
            usage.output_tokens = getattr(meta, "candidates_token_count", 0) or 0

        return response.text, usage

    # ------------------------------------------------------------------
    # Response parser
    # ------------------------------------------------------------------

    def _parse_segment_response(
        self, response_text: str, expected_type: str
    ) -> ScriptSegment:
        """APIレスポンスを ScriptSegment に変換"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError:
            cleaned = self._sanitize_json(response_text)
            data = json.loads(cleaned, strict=False)

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

    @staticmethod
    def _sanitize_json(text: str) -> str:
        """コードブロック等を除去してJSONを抽出"""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # 最初の ```... 行と最後の ``` 行を除去
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[start:end])
        return text
