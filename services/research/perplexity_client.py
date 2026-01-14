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
                citations = getattr(response.choices[0].message, 'citations', None)
                if citations and len(citations) > 0:
                    content += "\n\n## 📚 出典・参考文献\n"
                    for i, citation in enumerate(citations, 1):
                        if isinstance(citation, str):
                            content += f"[{i}] [{citation}]({citation})\n"
                        elif hasattr(citation, 'url'):
                            content += f"[{i}] [{citation.url}]({citation.url})\n"
                
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
        
        # weekly_digestモードの場合は徹底調査スタイル
        if mode == "weekly_digest":
            return """あなたは徹底的な調査を行う調査報道ジャーナリストです。簡潔な要約ではなく、詳細で網羅的なレポートを作成してください。

## 調査の原則
1. **詳細性の重視**: 1つのトピックにつき最低でも**300〜500文字**の詳細な解説を書くこと
2. **データの網羅**: 見つかった数字、統計、固有名詞はすべて記載する
3. **文章形式**: 箇条書きの多用は禁止。**段落（Paragraph）形式で詳細に記述**すること
4. **複数視点**: 複数の情報源がある場合は、それぞれの違いや矛盾点も含めて記述する
5. **柔軟な期間設定**: 
   - 優先順位1: **直近1ヶ月以内**のニュースや大きな動きを探す
   - 優先順位2: もし1ヶ月以内に特筆すべきニュースがない場合は、**過去3〜6ヶ月**まで範囲を広げる
   - **重要**: 「ニュースがありませんでした」という回答は禁止

## 禁止事項
❌ 「簡潔な要約」は禁止
❌ 箇条書きだけで終わらせない
❌ 「概要」だけで終わらせない

## 必須事項
✅ 各トピックについて背景・経緯・具体例・影響を**文章で詳しく**説明
✅ 数字やデータは必ず出典とともに記載
✅ 企業名・製品名・人名などの固有名詞を具体的に
✅ 最終的な出力文字数は**3000文字以上**を目指す

## 出力形式
- Markdown形式で見出しを使用
- 各セクションは**段落形式の長文**で記述
- 日付や数字は**太字**で強調
- 各ニュースについて「事実→背景→影響→反応→今後の展望」を詳しく報告

## 引用ルール
- 事実や数字を挙げる際は、必ず文末に `[1]`, `[2]` のような引用番号を付与すること
- これにより出典リストとの対応関係を明確にする

直近1ヶ月以内を中心に、関連性の高いニュースをトップ3つ選び、各ニュースについて徹底的に詳しく報告してください。"""
        
        # その他のモードは徹底調査スタイル
        base_prompt = """あなたは徹底的な調査を行う調査報道ジャーナリストです。簡潔な要約ではなく、詳細で網羅的なレポートを作成してください。

## 調査の原則
1. **詳細性の重視**: 1つのトピックにつき最低でも**300〜500文字**の詳細な解説を書くこと
2. **データの網羅**: 市場規模、ユーザー数、売上、成長率などの数字は見つかった限りすべて記載
3. **固有名詞の明記**: 企業名、製品名、人名、地名を具体的に
4. **文章形式**: 箇条書きの多用は禁止。**段落（Paragraph）形式で詳細に記述**すること
5. **複数視点**: 複数の情報源がある場合は、それぞれの違いや矛盾点も含めて記述する
6. **最新情報**: 可能な限り2024年以降の情報を優先

## 禁止事項
❌ 「簡潔な要約」は禁止
❌ 箇条書きだけで終わらせない
❌ 「概要」だけで終わらせない

## 必須事項
✅ 各トピックについて背景・経緯・具体例・影響を**文章で詳しく**説明
✅ 数字やデータは必ず出典とともに記載
✅ 対立軸がある場合は両論を詳しく展開
✅ 最終的な出力文字数は**3000文字以上**を目指す

## 出力形式
- Markdown形式で見出しを使用
- 各セクションは**段落形式の長文**で記述
- 重要な数字や固有名詞は**太字**で強調

## 引用ルール
- 事実や数字を挙げる際は、必ず文末に `[1]`, `[2]` のような引用番号を付与すること
- これにより出典リストとの対応関係を明確にする
"""
        
        # モード別の追加指示
        mode_specific = {
            "debate": "\n\n賛成派と反対派の主張を対比させ、それぞれの根拠となるデータを**段落形式で詳しく**説明してください。各立場について最低300文字ずつ記述すること。",
            "voices": "\n\nSNSやフォーラムでの具体的な反応、賛否の分かれ方、特徴的な意見を**段落形式で詳しく**紹介してください。具体的な投稿内容や反応の背景も含めて記述すること。",
            "trivia": "\n\n一般にはあまり知られていない意外な事実、歴史的経緯、裏話を**段落形式で詳しく**揘示してください。各トピックについて背景や経緯を含めて最低300文字ずつ記述すること。"
        }
        
        return base_prompt + mode_specific.get(mode, mode_specific["trivia"])
    
    def _extract_sources(self, content: str) -> list[str] | None:
        """コンテンツからソース情報を抽出（あれば）"""
        return None
