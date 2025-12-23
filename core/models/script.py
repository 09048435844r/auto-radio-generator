"""台本データモデル"""
from pydantic import BaseModel, Field
from typing import Literal, Optional


class DialogueLine(BaseModel):
    """対話の1行を表すモデル"""
    speaker_id: Literal["main", "sub"] = Field(
        description="話者ID: 'main' または 'sub'"
    )
    text: str = Field(
        description="セリフのテキスト"
    )
    section: Optional[str] = Field(
        default=None,
        description="セクション名（例: 'intro', 'news_1', 'ending'）。セクションの開始行に設定"
    )


class Script(BaseModel):
    """台本全体を表すモデル"""
    title: str = Field(
        description="YouTube動画のタイトル案"
    )
    thumbnail_title: str = Field(
        default="",
        description="サムネイル用の短い釣りタイトル（10〜15文字以内のキャッチコピー）"
    )
    description: str = Field(
        description="YouTubeの概要欄・ハッシュタグ案"
    )
    dialogue: list[DialogueLine] = Field(
        default_factory=list,
        description="対話リスト"
    )

    def to_prompt_format(self) -> str:
        """プロンプト表示用のフォーマット"""
        lines = [f"【タイトル】{self.title}", f"【概要】{self.description}", "", "【対話】"]
        for line in self.dialogue:
            lines.append(f"[{line.speaker_id}] {line.text}")
        return "\n".join(lines)
