"""MetadataGenerator - 台本完成後にメタデータを生成するエージェント

Hierarchical Agentic Workflow の後処理（ポストプロセス）。
完成したセリフ全編とリサーチデータを受け取り、以下を生成する:
  - 動画タイトル (title)
  - サムネイル用短いタイトル (thumbnail_title)
  - 概要欄テキスト (description) ※ 参考リンクを末尾に結合
  - ハッシュタグリスト (hashtags)
  - 参考文献URLリスト (references)

セグメント生成ロジックには一切影響を与えない独立した後処理として設計する。
"""
import json
import logging
import time
from typing import Optional, TYPE_CHECKING

from rich.console import Console
from pydantic import BaseModel, Field

from core.models import AppConfig, LLMUsage
from core.utils import sanitize_json_response

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

    def __init__(self, config: AppConfig):
        self.config = config

        # キュレーションと同じ軽量モデルを使用（コスト最適化）
        orch_cfg = config.yaml.script_generator.orchestrator
        self.model = orch_cfg.curator_model  # gemini-2.5-flash 等

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

        log("[cyan]🔖 メタデータ生成開始...[/cyan]")

        # セリフ全文の要約を作成（全文は長すぎるのでサンプリング）
        script_summary = self._build_script_summary(script)

        # API呼び出し
        prompt = self._build_prompt(theme, script_summary, research_data)
        response_text, usage = self._call_api(prompt)
        self.last_usage = usage

        # パース（themeを渡してフォールバック時に使用）
        metadata = self._parse_response(response_text, theme)

        # 参考リンクをフォーマット
        references = self._extract_references(research_data)
        formatted_links = self._format_references_for_description(references)

        # Script を更新（セリフ sections には一切触れない）
        script.title = metadata.title
        script.thumbnail_title = metadata.thumbnail_title
        script.description = metadata.description + formatted_links
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
        """メタデータ生成用プロンプトを構築"""
        prompt = (
            f"あなたはYouTubeラジオ動画のメタデータ専門家です。\n"
            f"完成した台本を読み、動画のメタデータ（タイトル・サムネイル・概要欄・ハッシュタグ）を生成してください。\n\n"
            f"## 動画のテーマ\n{theme}\n\n"
            f"## 台本サマリー（セリフ抜粋）\n{script_summary}\n\n"
            f"## メタデータ生成ルール\n"
            f"- title: 30〜45文字。「〜について話したら〜だった」「〜の真実」など視聴意欲を刺激するタイトル。\n"
            f"- thumbnail_title: サムネイル画像に載せる短いテキスト（15文字以内）。インパクト重視。\n"
            f"- description: YouTube概要欄。番組の内容・学びを300〜500文字でまとめる。読者が「見たい」と思う文章。\n"
            f"- hashtags: 日本語中心で5〜8個。動画内容に関連するもの。#は不要（後で付与する）。\n\n"
            f"## 禁止事項\n"
            f"- タイトルに「〜まとめ」「〜解説」など平凡な表現を使わない\n"
            f"- description に参考リンクを含めない（後で自動追加される）\n\n"
            f"## 出力形式（JSON）\n"
            f"純粋なJSONのみ出力。コードブロック不要。文字列内の改行は使用しないこと。\n"
            f'{{\n'
            f'  "title": "動画タイトル",\n'
            f'  "thumbnail_title": "短いタイトル",\n'
            f'  "description": "概要欄テキスト",\n'
            f'  "hashtags": ["タグ1", "タグ2", "タグ3"]\n'
            f'}}\n'
        )
        return prompt

    def _call_api(self, prompt: str) -> tuple[str, LLMUsage]:
        """Gemini APIを呼び出してメタデータを取得"""
        config_params = {
            "max_output_tokens": 4096,  # JSON途中切断を防ぐため増量（2048→4096）
            "temperature": 0.5,
            # response_mime_type は使用しない（JSON切断の原因となるため）
            "safety_settings": self.safety_settings,
        }

        max_retries = 2
        response = None
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[
                        self._types.Content(
                            role="user",
                            parts=[self._types.Part(text=prompt)]
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
                    console.print(f"[yellow]MetadataGenerator 接続エラー ({attempt + 1}/{max_retries})。{wait_time}秒後にリトライ...[/yellow]")
                    time.sleep(wait_time)
                    continue
                raise

        # finish_reasonをチェック（MAX_TOKENSの場合は警告）
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason and str(finish_reason) == "MAX_TOKENS":
                logger.warning(
                    f"⚠️ MetadataGenerator output was truncated (finish_reason=MAX_TOKENS). "
                    f"Consider increasing max_output_tokens."
                )

        usage = LLMUsage(
            provider="gemini",
            model_name=self.model,
            input_tokens=0,
            output_tokens=0,
            request_count=1,
        )
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage.input_tokens = getattr(meta, "prompt_token_count", 0) or 0
            usage.output_tokens = getattr(meta, "candidates_token_count", 0) or 0

        return response.text, usage

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


    @staticmethod
    def _format_references_for_description(references: list[str]) -> str:
        """参考URLリストを概要欄用テキストにフォーマット"""
        if not references:
            return ""

        lines = ["\n\n【参考文献・リンク】"]
        for url in references:
            lines.append(f"🔗 {url}")

        return "\n".join(lines)
