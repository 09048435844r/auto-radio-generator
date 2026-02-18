"""台本データモデル"""
from typing import List, Optional, Literal, Any, Dict
from pydantic import BaseModel, Field, field_validator, model_validator

# 話者IDの定義
SpeakerID = Literal["A", "B"]


class DialogueLine(BaseModel):
    """台本の1行（会話ターン）を表すモデル"""
    speaker: SpeakerID = Field(..., description="話者ID ('A' または 'B')")
    text: str = Field(..., min_length=1, description="セリフ本文（空文字不可）")
    emotion: Optional[str] = Field(None, description="感情指定（例: joy, sorrow, neutral）")
    section: Optional[str] = Field(None, description="セクションマーカー（チャプター用、例: intro, main_1, ending）")
    chapter_title: Optional[str] = Field(None, description="AI生成のチャプタータイトル（sectionがある場合に使用、15文字以内推奨）")
    
    # 後方互換性のため、古いJSON形式を自動変換
    @model_validator(mode='before')
    @classmethod
    def upgrade_legacy_data(cls, data: Any) -> Any:
        """既存のspeaker_id形式を新形式に変換"""
        if isinstance(data, dict):
            # speaker_id -> speaker 変換
            if 'speaker_id' in data and 'speaker' not in data:
                role = data.pop('speaker_id')
                if role == 'main':
                    data['speaker'] = 'A'
                elif role == 'sub':
                    data['speaker'] = 'B'
                else:
                    data['speaker'] = 'A'  # fallback
        return data
    
    # 後方互換性のため、speaker_idも受け入れる
    @field_validator('speaker', mode='before')
    @classmethod
    def convert_speaker_id(cls, v):
        """既存のspeaker_id形式を新形式に変換"""
        if v == "main":
            return "A"
        elif v == "sub":
            return "B"
        return v

    class Config:
        validate_assignment = True


class Script(BaseModel):
    """ラジオ台本全体を表すモデル"""
    title: str = Field(..., description="ラジオのタイトル")
    theme: str = Field(default="", description="今回のテーマ")
    sections: List[DialogueLine] = Field(..., min_length=10, description="会話のリスト（最低10ターン以上）")
    
    # メタデータ（デフォルトNone）
    thumbnail_title: Optional[str] = None
    description: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list, description="動画向けハッシュタグ一覧")
    references: List[str] = Field(default_factory=list, description="参考文献URL一覧")
    
    # 後方互換性のため、dialogueフィールドも受け入れる
    @model_validator(mode='before')
    @classmethod
    def convert_dialogue_to_sections(cls, data: Any) -> Any:
        """既存のdialogue形式をsectionsに変換"""
        if isinstance(data, dict):
            # dialogueフィールドがあり、sectionsがない場合
            if 'dialogue' in data and 'sections' not in data:
                data['sections'] = data.pop('dialogue')
        return data

    @property
    def total_turns(self) -> int:
        """総ターン数を返す"""
        return len(self.sections)
    
    @property
    def dialogue(self) -> List[DialogueLine]:
        """後方互換性のため、dialogueプロパティを提供"""
        return self.sections
    
    def to_prompt_format(self) -> str:
        """プロンプト表示用のフォーマット"""
        lines = [f"【タイトル】{self.title}", f"【概要】{self.description or ''}", "", "【対話】"]
        for line in self.sections:
            lines.append(f"[{line.speaker}] {line.text}")
        return "\n".join(lines)
