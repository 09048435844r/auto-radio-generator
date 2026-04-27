"""Perplexity APIを使用したリサーチクライアント"""
import asyncio
import os
import json
from pathlib import Path
from urllib.parse import urlparse
from openai import OpenAI
from rich.console import Console

from core.interfaces import IResearcher, ResearchResult, ResearchMode
from core.models import AppConfig, PerplexityUsage
from core.models.research import ResearchSource
from core.prompt_manager import PromptManager
from .title_fetcher import fetch_page_title

console = Console()


class PerplexityResearcher(IResearcher):
    """Perplexity APIを使用してテーマをリサーチする
    
    Perplexity APIはOpenAI互換APIとして提供されているため、
    OpenAIクライアントを使用してアクセスする。
    """
    
    PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        
        api_key = config.env.perplexity_api_key
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY が設定されていません")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.PERPLEXITY_BASE_URL
        )
        
        self.model = config.yaml.researcher.model
        self.max_tokens = config.yaml.researcher.max_tokens
        self.modes = config.yaml.researcher.modes
        self.max_queries_per_plan = max(1, int(getattr(config.yaml.researcher, "max_queries_per_plan", 3)))
        self.max_requests_per_workflow = max(1, int(getattr(config.yaml.researcher, "max_requests_per_workflow", 6)))
        self.enable_session_cache = bool(getattr(config.yaml.researcher, "enable_session_cache", True))
        self._session_request_count = 0
        self._session_cache: dict[tuple[str, tuple[str, ...]], ResearchResult] = {}
        self.prompt_manager = PromptManager()
        
        # 実行ログ用: プロンプト記録リスト
        self.prompt_records: list = []
    
    async def research(self, topic: str, mode: ResearchMode) -> ResearchResult:
        """テーマについてリサーチを実行する"""
        
        # Mock Mode Check
        mock_mode = self.config.yaml.dev.mock_mode if hasattr(self.config.yaml, 'dev') else False
        if mock_mode:
            mock_data_path = self.config.yaml.dev.mock_data_path if hasattr(self.config.yaml.dev, 'mock_data_path') else "tests/mock_data"
            mock_file = Path(mock_data_path) / "research.json"
            
            if mock_file.exists():
                console.print(f"[yellow]⚠ MOCK MODE: Using data from {mock_file}[/yellow]")
                with open(mock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Pydanticの後方互換性機能により、古い形式も自動変換される
                    return ResearchResult(**data)
            else:
                console.print(f"[red]✗ Mock data not found at {mock_file}[/red]")
                console.print(f"[yellow]  Falling back to normal API execution...[/yellow]")
        
        console.print(f"[cyan]Perplexity でリサーチ中...[/cyan]")
        console.print(f"  テーマ: {topic}")
        console.print(f"  モード: {mode}")

        if self._session_request_count + 1 > self.max_requests_per_workflow:
            raise RuntimeError(
                f"Perplexity呼び出し上限に達しました ({self._session_request_count}/{self.max_requests_per_workflow})。"
                " これ以上のリサーチは停止します。"
            )
        
        # モード設定からシステムプロンプトを取得
        mode_config = self.modes.get(mode)
        if mode_config:
            system_prompt = mode_config.system_prompt
        else:
            # PromptManagerからプロンプトを取得
            system_prompt = self.prompt_manager.get_research_prompt(mode)
        
        try:
            self._session_request_count += 1
            user_prompt = f"テーマ: {topic}"
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=0.7
            )
            
            content = response.choices[0].message.content
            
            # 実行ログ用: プロンプトとレスポンスを記録
            from datetime import datetime
            prompt_record = {
                "phase": "research",
                "api_provider": "perplexity",
                "model_name": self.model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "raw_response": content,
                "timestamp": datetime.now().isoformat()
            }
            self.prompt_records.append(prompt_record)
            
            # ソース情報の抽出（Perplexityの場合、レスポンスに含まれることがある）
            sources = self._extract_sources_from_citations(response)
            if not sources:
                sources = self._extract_sources(content)
            
            console.print(f"[green]✓ リサーチ完了[/green] ({len(content)}文字)")
            
            # 使用量を記録
            usage = PerplexityUsage(request_count=1)
            
            return ResearchResult(
                topic=topic,
                mode=mode,
                content=content,
                sources=sources,
                usage=usage
            )
            
        except Exception as e:
            error_type, error_message = self._classify_api_error(e)
            console.print(f"[red]✗ Perplexity API エラー ({error_type}): {error_message}[/red]")
            raise RuntimeError(error_message) from e
    
    async def check_api_status(self) -> bool:
        """APIの接続状態を確認する"""
        try:
            # 簡単なリクエストでAPIの可用性を確認
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5
            )
            return True
        except Exception as e:
            console.print(f"[red]Perplexity API 接続エラー: {e}[/red]")
            return False

    def _classify_api_error(self, error: Exception) -> tuple[str, str]:
        """Perplexity APIエラーを分類し、ユーザー向け文言を返す。"""
        error_text = str(error)
        error_text_lower = error_text.lower()
        status_code = getattr(error, "status_code", None)

        quota_markers = ["insufficient", "quota", "credit", "billing", "payment"]
        challenge_markers = ["cdn-cgi/challenge-platform", "openresty", "__cf$cv$params"]
        auth_markers = ["authenticationerror", "unauthorized", "invalid api key"]

        if status_code in (402, 429) or any(marker in error_text_lower for marker in quota_markers):
            return (
                "quota_exceeded",
                "Perplexityのクレジット不足または利用上限超過の可能性があります。"
                " 残高・課金設定・利用制限を確認してください。",
            )

        if any(marker in error_text_lower for marker in challenge_markers):
            return (
                "network_challenge",
                "Perplexity APIへの通信でCloudflare/WAFチャレンジを検知しました。"
                " VPN/Proxy/Firewall設定、ネットワーク経路を確認してください。",
            )

        if status_code == 401 or any(marker in error_text_lower for marker in auth_markers):
            return (
                "auth_failed",
                "Perplexity API認証に失敗しました。APIキーの有効性や権限を確認してください。",
            )

        return ("unknown", f"Perplexity APIエラー: {error_text}")
    
    async def research_multi(
        self,
        queries: list[str],
        mode: ResearchMode,
        avoid_topics: str | None = None
    ) -> ResearchResult:
        """複数のクエリを並列に実行して情報を収集
        
        Args:
            queries: 検索クエリのリスト
            mode: リサーチモード
            avoid_topics: 避けてほしい話題（除外要件、オプション）
        
        Returns:
            ResearchResult: 結合されたリサーチ結果
        """
        normalized_queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
        if not normalized_queries:
            raise RuntimeError("有効な検索クエリが存在しないため、リサーチを実行できません。")

        if len(normalized_queries) > self.max_queries_per_plan:
            console.print(
                f"[yellow]⚠ 検索クエリを上限 {self.max_queries_per_plan} 件に制限します"
                f" (入力: {len(normalized_queries)}件)[/yellow]"
            )
            normalized_queries = normalized_queries[:self.max_queries_per_plan]

        cache_key = (str(mode), tuple(normalized_queries))
        if self.enable_session_cache and cache_key in self._session_cache:
            cached = self._session_cache[cache_key]
            console.print("[cyan]Perplexityセッションキャッシュを再利用します（API呼び出しなし）[/cyan]")
            return ResearchResult(
                topic=cached.topic,
                mode=cached.mode,
                content=cached.content,
                sources=cached.sources,
                usage=PerplexityUsage(request_count=0),
            )

        planned_requests = len(normalized_queries)
        if self._session_request_count + planned_requests > self.max_requests_per_workflow:
            raise RuntimeError(
                "Perplexity呼び出し上限を超えるためリサーチを停止しました: "
                f"{self._session_request_count} + {planned_requests} > {self.max_requests_per_workflow}"
            )

        console.print(f"[cyan]Perplexity で並列リサーチ中...[/cyan]")
        console.print(f"  クエリ数: {len(normalized_queries)}")
        console.print(f"  モード: {mode}")
        
        # モード設定からシステムプロンプトを取得
        mode_config = self.modes.get(mode)
        if mode_config:
            system_prompt = mode_config.system_prompt
        else:
            # PromptManagerからプロンプトを取得
            system_prompt = self.prompt_manager.get_research_prompt(mode)
        
        # 各クエリを並列に実行
        async def fetch_single(query: str, index: int) -> tuple[int, str, list[ResearchSource], str | None, str | None]:
            console.print(f"  [{index+1}/{len(normalized_queries)}] {query}")
            try:
                # クエリに高密度ファクトシートの要求を追加
                detailed_query = f"""{query}

上記について、以下の要素を**すべて含めた**詳細なファクトシートをMarkdown形式で作成してください：

## 必須要素
1. **背景・文脈**: 歴史的経緯、技術的前提、社会的背景
2. **具体的な数字・統計**: 市場規模、成長率、ユーザー数、技術指標など
3. **実例・事例**: 具体的な企業名、製品名、プロジェクト名、成功/失敗事例
4. **影響・インパクト**: 業界への影響、社会的影響、経済的影響、技術的影響
5. **専門家の見解**: 研究者、業界関係者、アナリストの具体的な発言や評価（引用）
6. **最新動向**: 直近6ヶ月以内のニュース、発表、トレンド
7. **議論のポイント**: 賛否両論、未解決の課題、今後の展望

## 出力要件
- **最低文字数**: 2500文字以上
- **推奨文字数**: 3000-4000文字
- **形式**: Markdown（見出し・箇条書き・段落を適切に使用）
- **禁止事項**: 挨拶、前置き、締めの言葉は不要（事実のみを記述）

可能な限り詳細に、マニアックに、深く掘り下げてください。表層的な情報ではなく、専門家レベルの深い洞察を求めています。"""

                # avoid_topicsが指定されている場合は除外要件を追加
                if avoid_topics and avoid_topics.strip():
                    detailed_query += f"""

## 除外要件（最重要）
以下の話題は既に取り上げたため、**絶対に含めないでください**：
{avoid_topics.strip()}

上記以外の新しい情報・視点・切り口を提供してください。"""
                    console.print(f"  [dim]除外要件を適用: {avoid_topics.strip()[:50]}...[/dim]")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": detailed_query}
                    ],
                    max_tokens=self.max_tokens,
                    temperature=0.7
                )
                content = response.choices[0].message.content
                sources = self._extract_sources_from_citations(response)

                if sources:
                    content += "\n\n## 📚 出典・参考文献\n"
                    for i, source in enumerate(sources, 1):
                        content += f"[{i}] [{source.title}]({source.url})\n"
                    console.print(f"  [green]✓ 引用情報追加: {len(sources)}件[/green]")
                else:
                    console.print(f"  [yellow]⚠ 引用情報なし（Perplexity APIが返さなかった可能性）[/yellow]")
                
                console.print(f"  ✓ [{index+1}] 完了 ({len(content)}文字)")
                return (index, content, sources, None, None)
            except Exception as e:
                error_type, error_message = self._classify_api_error(e)
                console.print(f"  [red]✗ [{index+1}] エラー ({error_type}): {error_message}[/red]")
                return (index, f"[エラー: {query}]", [], error_message, error_type)
        
        # asyncio.gatherで並列実行
        self._session_request_count += planned_requests
        tasks = [fetch_single(q, i) for i, q in enumerate(normalized_queries)]
        results = await asyncio.gather(*tasks)
        
        # 結果をインデックス順にソートして結合
        results.sort(key=lambda x: x[0])
        combined_content = ""
        all_sources: list[ResearchSource] = []
        failures: list[tuple[int, str, str]] = []
        for i, (idx, content, sources, error_message, error_type) in enumerate(results):
            combined_content += f"\n\n## 検索結果 {i+1}: {normalized_queries[idx]}\n\n{content}"
            all_sources.extend(sources)
            if error_message:
                failures.append((idx, error_message, error_type or "unknown"))

        if failures:
            console.print(f"[yellow]⚠ 並列リサーチ失敗: {len(failures)}/{len(results)}件[/yellow]")

        if len(failures) == len(results):
            if any(error_type == "quota_exceeded" for _, _, error_type in failures):
                raise RuntimeError(
                    "Perplexityリサーチが全件失敗しました。クレジット不足または利用上限超過の可能性があります。"
                    " 残高・課金設定・利用制限を確認してください。"
                )
            if any(error_type == "network_challenge" for _, _, error_type in failures):
                raise RuntimeError(
                    "Perplexityリサーチが全件失敗しました。Cloudflare/WAFチャレンジを検知しました。"
                    " VPN/Proxy/Firewall設定、ネットワーク経路を確認してください。"
                )
            if any(error_type == "auth_failed" for _, _, error_type in failures):
                raise RuntimeError(
                    "Perplexityリサーチが全件失敗しました。APIキー認証に失敗しています。"
                    " APIキーの有効性・権限を確認してください。"
                )
            raise RuntimeError("Perplexity並列リサーチが全クエリで失敗しました。ログを確認してください。")
        
        console.print(f"[green]✓ 並列リサーチ完了[/green] (合計{len(combined_content)}文字)")
        
        # 使用量を記録
        usage = PerplexityUsage(request_count=len(normalized_queries))
        
        # タイトルが未設定のソースについて、実際のページタイトルを取得
        enhanced_sources = await self._enhance_sources_with_titles(all_sources)
        
        result = ResearchResult(
            topic=", ".join(normalized_queries),
            mode=mode,
            content=combined_content,
            sources=self._dedupe_sources(enhanced_sources) or None,
            usage=usage
        )

        if self.enable_session_cache:
            self._session_cache[cache_key] = ResearchResult(
                topic=result.topic,
                mode=result.mode,
                content=result.content,
                sources=result.sources,
                usage=None,
            )

        return result
    
    async def _enhance_sources_with_titles(self, sources: list[ResearchSource]) -> list[ResearchSource]:
        """URLから実際のページタイトルを取得してResearchSourceを更新する（並列処理）。"""
        if not sources:
            return sources
        
        # タイトルが未設定のソースのみ抽出
        urls_to_fetch = []
        sources_needing_titles = []
        
        for source in sources:
            if not source.title or source.title.strip() == "":
                urls_to_fetch.append(source.url)
                sources_needing_titles.append(source)
        
        if not urls_to_fetch:
            return sources
        
        try:
            # 並列でタイトル取得
            titles = await fetch_page_titles_async(urls_to_fetch)
            
            # 取得したタイトルでResearchSourceを更新
            for source, title in zip(sources_needing_titles, titles):
                source.title = title
                
            console.print(f"  [green]✓ タイトル取得完了: {len(titles)}件[/green]")
            
        except Exception as e:
            console.print(f"  [yellow]⚠ タイトル取得エラー（フォールバック使用）: {e}[/yellow]")
        
        return sources
    
    def _extract_sources_from_citations(self, response) -> list[ResearchSource]:
        """Perplexityレスポンスのcitation情報から構造化ソースを抽出する。"""
        message = response.choices[0].message

        citations = None
        for attr_name in ["citations", "citation", "sources", "references"]:
            citations = getattr(message, attr_name, None)
            if citations:
                console.print(f"  [dim]引用情報を '{attr_name}' 属性から取得[/dim]")
                break

        if not citations and hasattr(response, "citations"):
            citations = response.citations
            console.print("  [dim]引用情報をレスポンスルートから取得[/dim]")

        if not citations:
            return []

        sources: list[ResearchSource] = []
        for citation in citations:
            url = ""
            title = ""

            if isinstance(citation, str):
                url = citation.strip()
            elif hasattr(citation, "url"):
                url = (getattr(citation, "url", "") or "").strip()
                title = (getattr(citation, "title", "") or "").strip()
            elif isinstance(citation, dict):
                url = str(citation.get("url", "") or "").strip()
                title = str(citation.get("title", "") or "").strip()

            if not url:
                continue

            if not title:
                title = self._build_source_title(url)

            sources.append(ResearchSource(title=title, url=url))

        return self._dedupe_sources(sources)

    def _extract_sources(self, content: str) -> list[ResearchSource] | None:
        """コンテンツ中のMarkdownリンクからソース情報を抽出する（フォールバック）。"""
        if not content:
            return None

        import re

        matches = re.findall(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", content)
        if not matches:
            return None

        sources = [
            ResearchSource(
                title=(title or self._build_source_title(url)).strip(),
                url=url.strip(),
            )
            for title, url in matches
            if url and url.strip()
        ]
        deduped = self._dedupe_sources(sources)
        return deduped or None

    def _dedupe_sources(self, sources: list[ResearchSource]) -> list[ResearchSource]:
        """URL基準でソース重複を除去し、順序を維持する。"""
        seen: set[str] = set()
        deduped: list[ResearchSource] = []
        for source in sources:
            url = (source.url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(source)
        return deduped

    def _build_source_title(self, url: str) -> str:
        """タイトル未提供時にURLから実際のページタイトルを取得する。"""
        try:
            return fetch_page_title(url)
        except Exception:
            # フォールバック: ドメイン名
            parsed = urlparse(url)
            if parsed.netloc:
                return parsed.netloc
            return url
