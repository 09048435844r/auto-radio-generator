"""台本データモデル"""
from typing import List, Optional, Literal, Any, Dict
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator

# 話者IDの定義
SpeakerID = Literal["A", "B"]


class TurnType(str, Enum):
    """発話ターンの種別"""
    DIALOGUE = "dialogue"   # 通常の発話
    ACTION = "action"       # システムアクション（ジングル等）


class ActionType(str, Enum):
    """アクションの種別（将来拡張用）"""
    JINGLE = "jingle"           # 場面転換ジングル
    PAUSE = "pause"             # 無音（間）
    SOUND_EFFECT = "sfx"        # 効果音
    CHAPTER_MARKER = "chapter"  # チャプターマーカー（メタデータのみ）


class DialogueTurn(BaseModel):
    """台本の1行（会話ターンまたはアクション）を表すモデル"""
    # 基本フィールド（対話用）
    speaker: Optional[SpeakerID] = Field(None, description="話者ID ('A' または 'B') - 対話の場合のみ必須")
    text: Optional[str] = Field(None, description="セリフ本文 - 対話の場合のみ必須")
    
    # 種別フィールド
    turn_type: TurnType = Field(default=TurnType.DIALOGUE, description="ターンの種別")
    
    # アクション用フィールド
    action_type: Optional[ActionType] = Field(None, description="アクションの種別 - turn_type=ACTIONの場合に使用")
    action_path: Optional[str] = Field(None, description="アクションのファイルパス（例: ジングル音声ファイル）")
    action_duration: Optional[float] = Field(None, description="アクションの再生時間（秒）")
    
    # 共通フィールド
    emotion: Optional[str] = Field(None, description="感情指定（例: joy, sorrow, neutral）")
    section: Optional[str] = Field(None, description="セクションマーカー（チャプター用、例: intro, main_1, ending）")
    chapter_title: Optional[str] = Field(None, description="AI生成のチャプタータイトル（sectionがある場合に使用、15文字以内推奨）")
    
    # ヘルパーメソッド
    def is_dialogue(self) -> bool:
        """対話ターンか判定"""
        return self.turn_type == TurnType.DIALOGUE
    
    def is_action(self) -> bool:
        """アクションターンか判定"""
        return self.turn_type == TurnType.ACTION
    
    def is_jingle(self) -> bool:
        """ジングルアクションか判定"""
        return self.turn_type == TurnType.ACTION and self.action_type == ActionType.JINGLE
    
    # 後方互換性のため、古いJSON形式を自動変換
    @model_validator(mode='before')
    @classmethod
    def upgrade_legacy_data(cls, data: Any) -> Any:
        """既存のDialogueLine形式を新形式に変換"""
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
            
            # 古い形式でtextフィールドがある場合は対話ターンとして扱う
            if 'text' in data and 'turn_type' not in data:
                data['turn_type'] = TurnType.DIALOGUE
                
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


# 後方互換性のためのエイリアス
DialogueLine = DialogueTurn


class Script(BaseModel):
    """ラジオ台本全体を表すモデル"""
    title: str = Field(..., description="ラジオのタイトル")
    theme: str = Field(default="", description="今回のテーマ")
    sections: List[DialogueTurn] = Field(..., min_length=10, description="会話のリスト（最低10ターン以上）")
    
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
    def dialogue(self) -> List[DialogueTurn]:
        """後方互換性のため、dialogueプロパティを提供"""
        return self.sections
    
    # 新規ヘルパーメソッド
    def get_dialogue_only(self) -> List[DialogueTurn]:
        """対話ターンのみを抽出"""
        return [turn for turn in self.sections if turn.is_dialogue()]
    
    def get_actions(self) -> List[DialogueTurn]:
        """アクションターンのみを抽出"""
        return [turn for turn in self.sections if turn.is_action()]
    
    def get_jingles(self) -> List[DialogueTurn]:
        """ジングルアクションのみを抽出"""
        return [turn for turn in self.sections if turn.is_jingle()]
    
    def to_prompt_format(self) -> str:
        """プロンプト表示用のフォーマット"""
        lines = [f"【タイトル】{self.title}", f"【概要】{self.description or ''}", "", "【対話】"]
        for turn in self.sections:
            if turn.is_dialogue():
                lines.append(f"[{turn.speaker}] {turn.text}")
            elif turn.is_jingle():
                lines.append(f"[JINGLE] {turn.action_path or ''}")
        return "\n".join(lines)


# ジングル用ファクトリ関数
def create_jingle_turn(
    jingle_path: str,
    duration: Optional[float] = None,
    section: Optional[str] = None,
    chapter_title: Optional[str] = None
) -> DialogueTurn:
    """ジングルアクション用のDialogueTurnを作成"""
    return DialogueTurn(
        turn_type=TurnType.ACTION,
        action_type=ActionType.JINGLE,
        action_path=jingle_path,
        action_duration=duration,
        section=section,
        chapter_title=chapter_title
    )


def create_chapter_marker(
    chapter_title: str,
    section: str
) -> DialogueTurn:
    """チャプターマーカー用のDialogueTurnを作成"""
    return DialogueTurn(
        turn_type=TurnType.ACTION,
        action_type=ActionType.CHAPTER_MARKER,
        text=f"[Chapter: {chapter_title}]",
        section=section,
        chapter_title=chapter_title
    )
