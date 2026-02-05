"""台本生成インターフェース"""
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from core.models import Script, AppConfig

if TYPE_CHECKING:
    from .researcher import ResearchResult


class IScriptGenerator(ABC):
    """台本生成の抽象インターフェース
    
    将来的なエンジン変更（OpenAI, Claude等）に備えて
    抽象クラスとして定義。
    """
    
    def __init__(self, config: AppConfig):
        """
        Args:
            config: アプリケーション設定
        """
        self.config = config
    
    @abstractmethod
    async def generate(
        self,
        theme: str,
        research_data: Optional["ResearchResult"] = None
    ) -> Script:
        """テーマに基づいて台本を生成する
        
        Args:
            theme: 動画のテーマ・トピック
            research_data: リサーチ結果（オプション）
        
        Returns:
            Script: 生成された台本（タイトル、概要、対話）
        
        Raises:
            ScriptGenerationError: 生成に失敗した場合
        """
        pass
    
    def _build_system_prompt(self) -> str:
        """システムプロンプトを構築する"""
        personalities = self.config.yaml.personalities
        return f"""あなたはYouTubeラジオ番組の台本作家です。
2人のパーソナリティによる対話形式の台本を作成してください。

【パーソナリティ】
1. メイン ({personalities.main.name}): {personalities.main.description}
2. サブ ({personalities.sub.name}): {personalities.sub.description}

【出力形式】
必ず以下のJSON形式で出力してください。他の文章は一切不要です。

```json
{{
  "title": "YouTube動画のタイトル案（魅力的で視聴者の興味を引くもの）",
  "description": "YouTubeの概要欄テキスト。ハッシュタグも含める。",
  "dialogue": [
    {{"speaker": "A", "text": "セリフ..."}},
    {{"speaker": "B", "text": "セリフ..."}},
    ...
  ]
}}
```

【注意事項】
- 対話は自然で面白く、テンポよく進むようにする
- 各セリフは音声合成に適した長さ（1〜3文程度）にする
- 合計で3〜5分程度の動画になる分量（15〜25往復程度）
- JSONのみを出力し、前後の説明文は不要
"""
