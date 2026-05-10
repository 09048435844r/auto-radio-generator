"""MetadataGenerator - 台本完成後にメタデータを生成するエージェント

Hierarchical Agentic Workflow の後処理（ポストプロセス）。
完成したセリフ全編とリサーチデータを受け取り、以下を生成する:
  - 動画タイトル (title)
  - サムネイル用短いタイトル (thumbnail_title)
  - 概要欄テキスト (description) ※ 参考リンクを末尾に結合
  - ハッシュタグリスト (hashtags)
  - 参考文献URLリスト (references)

セグメント生成ロジックには一切影響を与えない独立した後処理として設計する。


Step 4 v2 (2026-05-10) @deprecated: 旧 Gemini 自動経路の構成要素のため deprecated 扱い。
HITL タブからのみ呼ばれる。新規開発では外部台本モード (services/pipeline/external_script_phase.py)
を推奨。物理削除は Step 5 で再評価予定。
"""
import json
import logging
import time
from typing import Optional, TYPE_CHECKING

from rich.console import Console
from pydantic import BaseModel, Field

from core.models import AppConfig, LLMUsage
from core.utils import sanitize_json_response
from core.interfaces.llm_port import ILLMPort, LLMRequest
from core.prompt_manager import PromptManager

if TYPE_CHECKING:
    from core.interfaces.researcher import ResearchResult
    from core.models.script import Script

logger = logging.getLogger(__name__)
console = Console()


class _MetadataSchema(BaseModel):
    """LLMから受け取るメタデータの構造化スキーマ（内部用）"""
    title: str = Field(description="動画タイトル（30〜45文字程度）")
    thumbnail_title: str = Field(description="サムネイル用短いタイトル（15文字以内）")
    description: str = Field(description="YouTube概要欄テキスト（300〜500文字、参考リンクは含めない）")
    hashtags: list[str] = Field(description="ハッシュタグのリスト（#なし、5〜8個）")


class MetadataGenerator:
    """台本完成後のメタデータを生成する後処理エージェント

    セグメント生成が完了した後に呼び出され、
    title / thumbnail_title / description / hashtags / references を
    Script オブジェクトに充填する。
    """

    def __init__(self, llm_port: ILLMPort, config: AppConfig):
        """Initialize MetadataGenerator with LLM port
        
        Args:
            llm_port: LLM port interface for provider-agnostic communication
            config: Application configuration
        """
        self._llm = llm_port
        self.config = config
        self.prompt_manager = PromptManager()

        # Use model from injected LLM port (already configured by orchestrator)
        self.model = llm_port.model_name

        # PR-D Issue C: max_tokens config 駆動化。旧ハードコード 2048 を既定値として踏襲
        orch_cfg = config.yaml.script_generator.orchestrator
        mg_cfg = getattr(orch_cfg, "metadata_generator", None)
        self.max_tokens = int(getattr(mg_cfg, "max_tokens", 2048) or 2048)

        # 最後の使用量を保持（オーケストレーターが累積するため）
        self.last_usage: Optional[LLMUsage] = None

    async def generate(
        self,
        theme: str,
        script: "Script",
        research_data: "ResearchResult",
        progress_log=None,
    ) -> "Script":
        """メタデータを生成して Script オブジェクトを上書きして返す

        Args:
            theme: 動画のテーマ
            script: セリフが充填済みの Script オブジェクト（title等は空）
            research_data: リサーチ結果（sources を参考リンクに使用）
            progress_log: ログ出力関数

        Returns:
            Script: title / thumbnail_title / description / hashtags / references が充填された Script
        """
        log = progress_log or (lambda msg: console.print(msg))

        log(f"[cyan]🔖 メタデータ生成開始 (provider={self._llm.provider_name})...[/cyan]")

        # セリフ全文の要約を作成（全文は長すぎるのでサンプリング）
        script_summary = self._build_script_summary(script)

        # API呼び出し（ローカルLLM・クラウドLLM共通）
        prompt = self._build_prompt(theme, script_summary, research_data)
        response_text, usage = await self._call_api(prompt)
        self.last_usage = usage

        # パース（themeを渡してフォールバック時に使用）
        metadata = self._parse_response(response_text, theme)

        # 参考リンクを抽出（descriptionには含めない）
        references = self._extract_references(research_data)

        # Script を更新（セリフ sections には一切触れない）
        script.title = metadata.title
        script.thumbnail_title = metadata.thumbnail_title
        script.description = metadata.description  # 参考リンクは含めない（build_video_descriptionで追加される）
        script.hashtags = [f"#{tag}" if not tag.startswith("#") else tag for tag in metadata.hashtags]
        script.references = references

        log(f"[green]✓ メタデータ生成完了: 「{metadata.title}」[/green]")
        return script

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_script_summary(self, script: "Script") -> str:
        """セリフ全文のサマリーを構築（最大3000文字）"""
        lines = []
        for turn in script.sections:
            if hasattr(turn, "text") and turn.text:
                speaker_label = "ずんだもん" if getattr(turn, "speaker", "") == "A" else "めたん"
                lines.append(f"{speaker_label}: {turn.text}")

        full_text = "\n".join(lines)
        if len(full_text) > 3000:
            # 冒頭・中盤・末尾をサンプリング
            third = len(lines) // 3
            sampled = lines[:10] + lines[third:third + 10] + lines[-10:]
            full_text = "\n".join(sampled) + f"\n...（全{len(lines)}ターン）"

        return full_text

    def _build_prompt(
        self,
        theme: str,
        script_summary: str,
        research_data: "ResearchResult",
    ) -> str:
        """メタデータ生成用プロンプトを構築（prompts.yamlから取得）"""
        base_prompt = self.prompt_manager.get_prompt("script", "metadata_generation")
        
        # プロンプトにコンテキスト情報を追加
        prompt = (
            f"{base_prompt}\n\n"
            f"## 動画のテーマ\n{theme}\n\n"
            f"## 台本サマリー（セリフ抜粋）\n{script_summary[:500]}\n\n"
            f"## 出力形式（JSON）\n"
            f"以下の形式で必ず出力してください。コードブロック不要。\n"
            f'{{\n'
            f'  "title": "ここにタイトル",\n'
            f'  "thumbnail_title": "ここに短いタイトル",\n'
            f'  "description": "ここに概要欄テキスト",\n'
            f'  "hashtags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"]\n'
            f'}}\n\n'
            f"## 例\n"
            f'{{\n'
            f'  "title": "AIの進化が止まらない！人類の未来はどうなる？",\n'
            f'  "thumbnail_title": "AI革命の真実",\n'
            f'  "description": "今回のずんだもんラジオでは、最新のAI技術について詳しく解説します。",\n'
            f'  "hashtags": ["AI", "技術", "未来", "ラジオ", "ずんだもん"]\n'
            f'}}\n'
        )
        return prompt

    async def _call_api(self, prompt: str) -> tuple[str, LLMUsage]:
        """Call LLM API via port interface"""
        request = LLMRequest(
            system_prompt="",  # MetadataGenerator uses user prompt only
            user_prompt=prompt,
            model=self.model,
            max_tokens=self.max_tokens,  # PR-D: config 駆動（旧ハードコード 2048）
            temperature=0.6,  # Balanced: creative enough, stable enough
            response_format="json"
        )

        response = await self._llm.generate(request)

        # PR-D Issue C: fail-fast on truncation. The caller (scripting_phase / orchestrator)
        # already wraps this with try/except and falls back to default metadata, so the
        # user-visible behavior is identical ("using defaults") but we avoid attempting to
        # parse a truncated JSON (which could silently return a half-formed title).
        # PR-F: logger.error も併用して PR-C の processing_log.txt 収集に乗せる。
        if response.finish_reason == "length":
            msg = (
                "MetadataGenerator output was truncated (finish_reason=length). "
                f"Current max_tokens={self.max_tokens}. "
                "Increase orchestrator.metadata_generator.max_tokens in config.yaml. "
                "Caller will fall back to default metadata."
            )
            logger.error(msg)
            raise RuntimeError(msg)
        
        logger.debug(
            f"MetadataGenerator API: provider={response.usage.provider}, model={response.usage.model_name}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
        )
        
        return response.content, response.usage

    def _parse_response(self, response_text: str, theme: str) -> _MetadataSchema:
        """APIレスポンスを _MetadataSchema にパース"""
        try:
            data = json.loads(response_text.strip(), strict=False)
        except json.JSONDecodeError as e:
            # JSONパースエラー時の詳細ログ（デバッグ用）
            logger.error(f"[MetadataGenerator] JSON parse error: {e}")
            logger.error(f"[MetadataGenerator] Error position: line {e.lineno}, column {e.colno}, char {e.pos}")
            
            # 完全な生のレスポンステキストを出力（重要：人間がエラー箇所を特定できるように）
            logger.error(f"[MetadataGenerator] Full raw response text ({len(response_text)} chars):\n{'='*80}\n{response_text}\n{'='*80}")
            
            # 強力なサニタイズ処理を試行
            console.print(f"[yellow]⚠️ MetadataGenerator JSONパースエラー。サニタイズ処理を試行中...[/yellow]")
            cleaned = sanitize_json_response(response_text, "MetadataGenerator")
            logger.debug(f"[MetadataGenerator] Sanitized text ({len(cleaned)} chars):\n{cleaned[:1000]}...")
            
            try:
                data = json.loads(cleaned.strip(), strict=False)
                console.print(f"[green]✓ サニタイズ後のパースに成功[/green]")
            except json.JSONDecodeError as e2:
                logger.error(f"[MetadataGenerator] JSON parse failed after sanitization: {e2}")
                logger.error(f"[MetadataGenerator] Sanitized text:\n{'='*80}\n{cleaned}\n{'='*80}")
                console.print(f"[yellow]⚠️ サニタイズ後もJSONパースに失敗。フォールバックメタデータを使用します[/yellow]")
                console.print(f"[yellow]生のレスポンステキストをログファイルで確認してください[/yellow]")
                logger.warning(f"[MetadataGenerator] Using fallback metadata for theme: {theme}")
                
                # フォールバック: themeを活用した安全なデフォルト値を生成
                # YouTube投稿時のエラーを防ぐため、空文字列ではなく意味のある値を返す
                fallback_title = f"{theme}について" if len(theme) <= 40 else f"{theme[:37]}..."
                fallback_thumbnail = theme[:15] if len(theme) <= 15 else theme[:12] + "..."
                fallback_description = f"「{theme}」について、ずんだもんとめたんが詳しく解説します。"
                fallback_hashtags = ["解説", "ラジオ", "AI生成"]
                
                return _MetadataSchema(
                    title=fallback_title,
                    thumbnail_title=fallback_thumbnail,
                    description=fallback_description,
                    hashtags=fallback_hashtags,
                )

        # 正常パース時もデフォルト値を設定（空文字列を防ぐ）
        return _MetadataSchema(
            title=data.get("title", "") or f"{theme}について",
            thumbnail_title=data.get("thumbnail_title", "") or theme[:15],
            description=data.get("description", "") or f"「{theme}」に関する解説動画です。",
            hashtags=data.get("hashtags", []) or ["解説", "ラジオ"],
        )

    @staticmethod
    def _extract_references(research_data: "ResearchResult") -> list[str]:
        """ResearchResult から参考URLリストを抽出"""
        sources = getattr(research_data, "sources", None)
        if not sources:
            return []

        urls = []
        for source in sources:
            if hasattr(source, "url") and source.url:
                urls.append(source.url)

        # 重複除去・順序保持
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls[:10]  # 最大10件
