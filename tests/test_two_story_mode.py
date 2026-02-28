import pytest
from core.models.script import Script, DialogueTurn, TurnType, ActionType

from workflow import _merge_scripts, _create_script_summary

def _make_dialogues(prefix: str, speaker: str, count: int = 10) -> list[DialogueTurn]:
    return [
        DialogueTurn(speaker=speaker, text=f"{prefix}{i}", section=f"sec_{prefix}_{i}")
        for i in range(count)
    ]

def test_script_merging_with_jingle():
    """2つの台本がジングルを挟んで正しく結合されるかテスト"""
    # Pydanticモデルの場合はキーワード引数で初期化
    script1 = Script(
        title="Part 1", theme="Theme", thumbnail_title="T1", description="Desc 1",
        references=[],
        dialogue=_make_dialogues("こんにちは1-", "A")
    )
    script2 = Script(
        title="Part 2", theme="Theme", thumbnail_title="T2", description="Desc 2",
        references=[],
        dialogue=_make_dialogues("こんにちは2-", "B")
    )
    
    jingle_path = "assets/jingles/test.mp3"
    
    # 2. 結合の実行
    merged = _merge_scripts([script1, script2], jingle_path=jingle_path)
    
    # 3. 検証 (get_dialogue_only() 等のメソッドも確認)
    dialogue_only = merged.get_dialogue_only()
    assert dialogue_only[0].text == "こんにちは1-0"
    
    # ジングルが挿入されているか (is_jingle メソッドを使用)
    jingles = [t for t in merged.dialogue if t.is_jingle()]
    assert len(jingles) == 1
    assert jingles[0].action_path == jingle_path
    
    assert dialogue_only[-1].text == "こんにちは2-9"

def test_script_summary_generation():
    """要約生成のテスト"""
    script = Script(
        title="サプリの話", theme="Health", thumbnail_title="T", description="D",
        references=[],
        dialogue=[
            DialogueTurn(speaker="A", text="NMNは若返りのサプリです。", section="基礎知識")
        ] + _make_dialogues("補足-", "B", count=9)
    )
    
    summary = _create_script_summary(script)
    assert "セクション:" in summary
    assert "NMN" in summary