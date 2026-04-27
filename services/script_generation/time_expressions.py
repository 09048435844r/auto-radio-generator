"""モード別の時間表現定義

各リサーチモードで使用する時間に関する表現を一元管理する。
これにより、プロンプト内の時間表現を動的に変更できる。
"""

from typing import TypedDict


class TimeExpression(TypedDict):
    """時間表現の型定義"""
    title_prefix: str        # タイトルの接頭辞（例: 「最近の」「今週の」）
    intro_phrase: str        # イントロでの表現
    outro_phrase: str        # アウトロでの表現
    period_description: str  # 期間の説明


# モード別の時間表現
TIME_EXPRESSIONS: dict[str, TimeExpression] = {
    "weekly_digest": {
        "title_prefix": "最近の",
        "intro_phrase": "最近の",
        "outro_phrase": "最近の",
        "period_description": "直近1ヶ月以内を中心に、関連性の高い"
    },
    "trivia": {
        "title_prefix": "",
        "intro_phrase": "",
        "outro_phrase": "",
        "period_description": "興味深い"
    },
    "debate": {
        "title_prefix": "",
        "intro_phrase": "",
        "outro_phrase": "",
        "period_description": "議論を呼ぶ"
    },
    "voices": {
        "title_prefix": "",
        "intro_phrase": "",
        "outro_phrase": "",
        "period_description": "話題の"
    },
    "lecture": {
        "title_prefix": "",
        "intro_phrase": "",
        "outro_phrase": "",
        "period_description": "分かりやすい"
    }
}


def get_time_expression(mode: str) -> TimeExpression:
    """モードに対応する時間表現を取得
    
    Args:
        mode: リサーチモード (trivia/debate/weekly_digest/voices/lecture)
    
    Returns:
        TimeExpression: 時間表現の辞書
    """
    return TIME_EXPRESSIONS.get(mode, TIME_EXPRESSIONS["trivia"])
