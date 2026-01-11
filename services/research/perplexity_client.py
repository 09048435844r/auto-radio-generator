"""Perplexity APIを使用したリサーチクライアント"""
import asyncio
from openai import OpenAI
from rich.console import Console

from core.interfaces import IResearcher, ResearchResult, ResearchMode
from core.models import AppConfig, PerplexityUsage

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
    
    async def research(self, topic: str, mode: ResearchMode) -> ResearchResult:
        """テーマについてリサーチを実行する"""
        console.print(f"[cyan]Perplexity でリサーチ中...[/cyan]")
        console.print(f"  テーマ: {topic}")
        console.print(f"  モード: {mode}")
        
        # モード設定からシステムプロンプトを取得
        mode_config = self.modes.get(mode)
        if mode_config:
            system_prompt = mode_config.system_prompt
        else:
            system_prompt = self._get_default_system_prompt(mode)
        
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
            system_prompt = self._get_default_system_prompt(mode)
        
        # 各クエリを並列に実行
        async def fetch_single(query: str, index: int) -> tuple[int, str]:
            console.print(f"  [{index+1}/{len(queries)}] {query}")
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query}
                    ],
                    max_tokens=self.max_tokens,
                    temperature=0.7
                )
                content = response.choices[0].message.content
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
    
    def _get_default_system_prompt(self, mode: ResearchMode) -> str:
        """デフォルトのシステムプロンプトを取得（モード別に切り替え）"""
        
        # weekly_digestモードの場合はニュースキャスタースタイル
        if mode == "weekly_digest":
            return """あなたはニュースキャスターです。正確性と時系列を重視した報道を行ってください。

## 報道の原則
1. **時系列の明確化**: いつ起きたことなのかを明記（「今週月曜日」「昨日」など）
2. **事実の正確性**: 確認された事実のみを報道し、憶測は避ける
3. **5W1H**: Who（誰が）、What（何を）、When（いつ）、Where（どこで）、Why（なぜ）、How（どのように）を明確に
4. **最新情報優先**: 直近1週間以内の情報を最優先

## 出力形式
- Markdown形式で見出しと箇条書きを使用
- 日付や時刻は**太字**で強調
- 時系列順に整理して報道
- 各ニュースについて「事実→背景→影響→反応」の順で構成

直近1週間以内のニュースをトップ3つ選び、各ニュースについて事実・背景・影響・反応を詳しく報告してください。"""
        
        # その他のモードは週刊誌記者モード
        base_prompt = """あなたは週刊誌の記者です。読者が食いつく「具体的で刺激的な情報」を提供してください。

## 取材の原則
1. **数字を重視**: 市場規模、ユーザー数、売上、成長率などの具体的な数値を提示
2. **固有名詞を明記**: 企業名、製品名、人名、地名を具体的に
3. **対立軸を探る**: メリットだけでなくデメリット、賛否両論、利害関係を揘示
4. **最新情報**: 可能な限り2024年以降の情報を優先

## 出力形式
- Markdown形式で見出しと箇条書きを使用
- 重要な数字や固有名詞は**太字**で強調
- ベタ書きの長文は避け、読みやすく構造化
"""
        
        # モード別の追加指示
        mode_specific = {
            "debate": "\n賛成派と反対派の主張を対比させ、それぞれの根拠となるデータを提示してください。",
            "voices": "\nSNSやフォーラムでの具体的な反応、賛否の分かれ方、特徴的な意見を紹介してください。",
            "trivia": "\n一般にはあまり知られていない意外な事実、歴史的経緯、裏話を揘示してください。"
        }
        
        return base_prompt + mode_specific.get(mode, mode_specific["trivia"])
    
    def _extract_sources(self, content: str) -> list[str] | None:
        """コンテンツからソース情報を抽出（あれば）"""
        return None
