"""TopicCurator - リサーチデータから面白いトピックを選定するエージェント

Hierarchical Agentic Workflow の Step 1。
膨大なリサーチデータを受け取り、ずんだもんとめたんが深く語り合うべき
2〜3個のトピックを意外性・具体性・議論性の3軸で評価・選定する。
"""
import json
import logging
from typing import Optional, TYPE_CHECKING

from rich.console import Console

from core.models import AppConfig, LLMUsage
from core.models.curation import CuratedTopic, CurationResult
from core.prompt_manager import PromptManager

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult

logger = logging.getLogger(__name__)
console = Console()


class TopicCurator:
    """リサーチデータから面白いトピックを選定するエージェント

    軽量モデル（gemini-2.5-flash 等）を使用してコストを抑えながら、
    後続の SegmentGenerator に渡す「厳選済みトピック」を生成する。
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.prompt_manager = PromptManager()

        # オーケストレーター設定からキュレーター用モデルを取得
        orch_cfg = config.yaml.script_generator.orchestrator
        self.curator_model = orch_cfg.curator_model
        self.max_topics = orch_cfg.max_topics

        # Gemini クライアントを初期化
        from google import genai
        from google.genai import types
        self._genai = genai
        self._types = types
        self.client = genai.Client(api_key=config.env.gemini_api_key)

        # セーフティ設定（医療系ワード等での誤爆防止）
        self.safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        ]

        self.last_usage: Optional[LLMUsage] = None

    async def curate_topics(
        self,
        research_data: "ResearchResult",
        target_count: Optional[int] = None,
        progress_log=None,
    ) -> CurationResult:
        """リサーチデータから面白いトピックを選定する

        Args:
            research_data: Perplexityから得たリサーチ結果
            target_count: 選定するトピック数（Noneの場合は設定値を使用）
            progress_log: 進捗ログ関数（オプション）

        Returns:
            CurationResult: 選定されたトピックと選定理由
        """
        count = target_count or self.max_topics
        log = progress_log or (lambda msg: console.print(msg))

        log(f"[cyan]🔍 トピックキュレーション開始 (モデル: {self.curator_model})[/cyan]")
        log(f"  リサーチデータ: {len(research_data.content)}文字 → {count}トピックを選定")

        system_prompt = self.prompt_manager.get_prompt("orchestrator", "curation")
        user_prompt = self._build_curation_user_prompt(research_data, count)

        try:
            response_text, usage = self._call_api(system_prompt, user_prompt)
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
    ) -> str:
        """キュレーション用ユーザープロンプトを構築"""
        prompt = f"## テーマ\n{research_data.mode}モードでリサーチされたデータです。\n\n"
        prompt += f"## リサーチデータ（全文）\n{research_data.content}\n\n"
        prompt += (
            f"## 指示\n"
            f"上記のリサーチデータから、最も面白い**{target_count}個**のトピックを選定してください。\n"
            f"評価軸（意外性・具体性・議論性）で採点し、上位{target_count}個を選ぶこと。\n\n"
            f"## 出力形式（JSON）\n"
            f"純粋なJSONのみ出力。コードブロック不要。\n"
            f"{{\n"
            f'  "topics": [\n'
            f'    {{\n'
            f'      "title": "トピックタイトル",\n'
            f'      "content": "詳細情報（500〜800文字）",\n'
            f'      "priority": 1,\n'
            f'      "estimated_turns": 30,\n'
            f'      "tone": "驚き",\n'
            f'      "key_facts": ["ファクト1", "ファクト2", "ファクト3"]\n'
            f'    }}\n'
            f'  ],\n'
            f'  "curator_reasoning": "選定理由（デバッグ用）"\n'
            f"}}\n"
        )
        return prompt

    def _call_api(self, system_prompt: str, user_prompt: str) -> tuple[str, LLMUsage]:
        """Gemini APIを呼び出してキュレーション結果を取得"""
        import time

        config_params = {
            "max_output_tokens": 4096,
            "temperature": 0.3,  # キュレーションは低温度で安定性を確保
            "response_mime_type": "application/json",
            "safety_settings": self.safety_settings,
        }

        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.curator_model,
                    contents=[
                        self._types.Content(
                            role="user",
                            parts=[self._types.Part(text=f"{system_prompt}\n\n{user_prompt}")]
                        )
                    ],
                    config=self._types.GenerateContentConfig(**config_params)
                )
                break
            except Exception as e:
                error_msg = str(e).lower()
                if ("disconnected" in error_msg or "timeout" in error_msg or "connection" in error_msg) \
                        and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    console.print(f"[yellow]接続エラー ({attempt + 1}/{max_retries})。{wait_time}秒後にリトライ...[/yellow]")
                    time.sleep(wait_time)
                    continue
                raise

        usage = LLMUsage(
            provider="gemini",
            model_name=self.curator_model,
            input_tokens=0,
            output_tokens=0,
            request_count=1,
        )
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage.input_tokens = getattr(meta, "prompt_token_count", 0) or 0
            usage.output_tokens = getattr(meta, "candidates_token_count", 0) or 0

        logger.debug(
            f"TopicCurator API: model={self.curator_model}, "
            f"in={usage.input_tokens}, out={usage.output_tokens}"
        )
        return response.text, usage

    def _parse_curation_response(self, response_text: str) -> CurationResult:
        """APIレスポンスを CurationResult に変換"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError:
            # コードブロックが混入している場合のサニタイズ
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(cleaned, strict=False)

        topics_data = data.get("topics", [])
        topics = []
        for t in topics_data:
            topics.append(CuratedTopic(
                title=t.get("title", ""),
                content=t.get("content", ""),
                priority=t.get("priority", len(topics) + 1),
                estimated_turns=t.get("estimated_turns", 30),
                tone=t.get("tone", "解説"),
                key_facts=t.get("key_facts", []),
            ))

        # 優先度でソート
        topics.sort(key=lambda x: x.priority)

        return CurationResult(
            topics=topics,
            curator_reasoning=data.get("curator_reasoning", ""),
        )
