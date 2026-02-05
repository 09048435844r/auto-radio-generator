"""Perplexity APIを使用したリサーチクライアント"""
import asyncio
import os
import json
from pathlib import Path
from openai import OpenAI
from rich.console import Console

from core.interfaces import IResearcher, ResearchResult, ResearchMode
from core.models import AppConfig, PerplexityUsage
from core.prompt_manager import PromptManager

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
        self.prompt_manager = PromptManager()
    
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
        
        # モード設定からシステムプロンプトを取得
        mode_config = self.modes.get(mode)
        if mode_config:
            system_prompt = mode_config.system_prompt
        else:
            # PromptManagerからプロンプトを取得
            system_prompt = self.prompt_manager.get_research_prompt(mode)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"テーマ: {topic}"}
                ],
                max_tokens=self.max_tokens,
                temperature=0.7
            )
            
            content = response.choices[0].message.content
            
            # ソース情報の抽出（Perplexityの場合、レスポンスに含まれることがある）
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
            console.print(f"[red]✗ Perplexity API エラー: {e}[/red]")
            raise
    
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
    
    async def research_multi(self, queries: list[str], mode: ResearchMode) -> ResearchResult:
        """複数のクエリを並列に実行して情報を収集
        
        Args:
            queries: 検索クエリのリスト
            mode: リサーチモード
        
        Returns:
            ResearchResult: 結合されたリサーチ結果
        """
        console.print(f"[cyan]Perplexity で並列リサーチ中...[/cyan]")
        console.print(f"  クエリ数: {len(queries)}")
        console.print(f"  モード: {mode}")
        
        # モード設定からシステムプロンプトを取得
        mode_config = self.modes.get(mode)
        if mode_config:
            system_prompt = mode_config.system_prompt
        else:
            # PromptManagerからプロンプトを取得
            system_prompt = self.prompt_manager.get_research_prompt(mode)
        
        # 各クエリを並列に実行
        async def fetch_single(query: str, index: int) -> tuple[int, str]:
            console.print(f"  [{index+1}/{len(queries)}] {query}")
            try:
                # クエリに詳細要求を追加
                detailed_query = f"{query}\n\n上記について、背景・数字・事例・影響を含めて可能な限り詳細に、長文で解説してください。最低でも500文字以上の詳しい説明をお願いします。"
                
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
                
                # 引用情報を抽出して追記
                # Perplexity APIのレスポンス構造をデバッグ
                message = response.choices[0].message
                
                # 複数の可能性のある属性名をチェック
                citations = None
                for attr_name in ['citations', 'citation', 'sources', 'references']:
                    citations = getattr(message, attr_name, None)
                    if citations:
                        console.print(f"  [dim]引用情報を '{attr_name}' 属性から取得[/dim]")
                        break
                
                # レスポンスオブジェクト全体から引用を探す
                if not citations and hasattr(response, 'citations'):
                    citations = response.citations
                    console.print(f"  [dim]引用情報をレスポンスルートから取得[/dim]")
                
                if citations and len(citations) > 0:
                    content += "\n\n## 📚 出典・参考文献\n"
                    for i, citation in enumerate(citations, 1):
                        if isinstance(citation, str):
                            content += f"[{i}] [{citation}]({citation})\n"
                        elif hasattr(citation, 'url'):
                            content += f"[{i}] [{citation.url}]({citation.url})\n"
                        elif isinstance(citation, dict) and 'url' in citation:
                            content += f"[{i}] [{citation['url']}]({citation['url']})\n"
                    console.print(f"  [green]✓ 引用情報追加: {len(citations)}件[/green]")
                else:
                    console.print(f"  [yellow]⚠ 引用情報なし（Perplexity APIが返さなかった可能性）[/yellow]")
                
                console.print(f"  ✓ [{index+1}] 完了 ({len(content)}文字)")
                return (index, content)
            except Exception as e:
                console.print(f"  [red]✗ [{index+1}] エラー: {e}[/red]")
                return (index, f"[エラー: {query}]")
        
        # asyncio.gatherで並列実行
        tasks = [fetch_single(q, i) for i, q in enumerate(queries)]
        results = await asyncio.gather(*tasks)
        
        # 結果をインデックス順にソートして結合
        results.sort(key=lambda x: x[0])
        combined_content = ""
        for i, (idx, content) in enumerate(results):
            combined_content += f"\n\n## 検索結果 {i+1}: {queries[idx]}\n\n{content}"
        
        console.print(f"[green]✓ 並列リサーチ完了[/green] (合計{len(combined_content)}文字)")
        
        # 使用量を記録
        usage = PerplexityUsage(request_count=len(queries))
        
        return ResearchResult(
            topic=", ".join(queries),
            mode=mode,
            content=combined_content,
            sources=None,
            usage=usage
        )
    
    def _extract_sources(self, content: str) -> list[str] | None:
        """コンテンツからソース情報を抽出（あれば）"""
        return None
