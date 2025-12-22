"""Perplexity APIを使用したリサーチクライアント"""
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
    
    def _get_default_system_prompt(self, mode: ResearchMode) -> str:
        """デフォルトのシステムプロンプトを取得"""
        prompts = {
            "debate": """あなたは議論の専門家です。与えられたテーマについて、
賛成・反対両方の視点から調査し、議論のポイントを整理してください。
結果は日本語で出力してください。""",
            
            "voices": """あなたはSNSアナリストです。与えられたテーマについて、
一般の人々の反応や意見、面白いコメントを調査してください。
結果は日本語でカジュアルに出力してください。""",
            
            "trivia": """あなたは雑学の専門家です。与えられたテーマについて、
あまり知られていない事実や歴史的背景を調査してください。
結果は日本語で「へぇ〜」と言いたくなるような形式で出力してください。""",
            
            "weekly_digest": """あなたはニュースキュレーターです。
与えられたトピックに関連する「直近1週間以内の重要な出来事」をトップ3つ選定してください。

各ニュースについて以下のフォーマットで出力：
### News 1: [見出し]
- **事実 (The Facts)**: 5W1H（いつ、どこで、誰が、何をしたか）を具体的に。
- **背景 (Context)**: なぜこれが今話題なのか？ これまでの経緯。
- **影響 (Impact)**: 今後どうなるか？ ユーザーや業界へのメリット・デメリット。
- **反応 (Reactions)**: SNSや専門家の具体的な反応。

### News 2: [見出し]
(同上のフォーマット)

### News 3: [見出し]
(同上のフォーマット)"""
        }
        return prompts.get(mode, prompts["trivia"])
    
    def _extract_sources(self, content: str) -> list[str] | None:
        """コンテンツからソース情報を抽出（あれば）"""
        # Perplexityのレスポンスにソースが含まれる場合の処理
        # 現時点では簡易実装
        return None
