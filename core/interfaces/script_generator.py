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
    
    def _build_part2_system_prompt(self) -> str:
        """Build Part 2 mode enhanced system prompt (shared across all providers)"""
        return """あなたはプロのラジオ台本作家です。現在、番組の第2部を制作しています。

【重要】第1部で放送済みの全内容がユーザープロンプトで提供されます。これを以下のルールで徹底的に活用してください：

1. 【前提知識の活用】
   - 第1部で説明済みの内容は、既に視聴者が知っている前提知識として扱ってください
   - 同じ説明や定義を繰り返さず、その知識を土台としてさらに深掘りしてください

2. 【重複の物理的回避】
   - 第1部で使われた具体的な例え、データ、フレーズは絶対に再利用しないでください
   - 同じトピックを扱う場合でも、全く異なる角度、別の視点、新しい情報を提供してください

3. 【一貫性の維持】
   - 第1部で確立した定義や世界観と矛盾しない、一貫性のある言い回しを徹底してください
   - キャラクターの口調や人格設定は第1部から継続してください

4. 【連続性の演出】
   - 可能であれば第1部の内容に軽く触れる（コールバックする）ことで、
     一つの番組としての自然な繋がりを演出してください
   - 「先ほどお話しした〇〇ですが、さらに深掘りすると…」のような自然な接続を心がけてください

5. 【価値の追加】
   - 第1部では触れられなかった側面、背景、応用例、将来展望などを提供してください
   - 視聴者が「第1部で知っていたことの全く新しい側面が見えた」と感じるような内容を目指してください

これらの制約を守りながら、第1部と合わせてあたかも一人の放送作家が一気に書き上げたような、
淀みのないスムーズな番組を制作してください。"""
