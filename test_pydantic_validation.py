"""Pydanticモデルの動作確認テスト

このスクリプトは、新しく導入したPydanticモデルが正しく機能しているかを確認します。
- DialogueLineモデルの検証
- Scriptモデルの検証
- 後方互換性の確認
- ResearchResultモデルの検証
"""
import json
from pathlib import Path
import sys

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models.script import DialogueLine, Script, SpeakerID
from core.models.research import ResearchSource, ResearchResult
from pydantic import ValidationError


def test_dialogue_line():
    """DialogueLineモデルのテスト"""
    print("\n=== DialogueLine モデルテスト ===")
    
    # 正常なケース
    try:
        line = DialogueLine(speaker="A", text="こんにちは！")
        print(f"[OK] 正常なDialogueLine作成成功: {line.speaker} - {line.text}")
    except Exception as e:
        print(f"[FAIL] エラー: {e}")
    
    # 後方互換性テスト（speaker_id="main" → speaker="A"）
    try:
        line_compat = DialogueLine(speaker="main", text="互換性テスト")
        print(f"[OK] 後方互換性OK: speaker_id='main' -> speaker='{line_compat.speaker}'")
    except Exception as e:
        print(f"[FAIL] 後方互換性エラー: {e}")
    
    # 空文字のテスト（失敗するはず）
    try:
        line_empty = DialogueLine(speaker="A", text="")
        print(f"[FAIL] 空文字が許可されてしまった: {line_empty}")
    except ValidationError as e:
        print(f"[OK] 空文字を正しく拒否: {e.error_count()} errors")
    
    # 不正な話者IDのテスト（失敗するはず）
    try:
        line_invalid = DialogueLine(speaker="C", text="不正な話者")
        print(f"[FAIL] 不正な話者IDが許可されてしまった: {line_invalid}")
    except ValidationError as e:
        print(f"[OK] 不正な話者IDを正しく拒否: {e.error_count()} errors")


def test_script_model():
    """Scriptモデルのテスト"""
    print("\n=== Script モデルテスト ===")
    
    # 正常なケース
    try:
        script = Script(
            title="テストラジオ",
            theme="Pydanticの威力",
            sections=[
                DialogueLine(speaker="A", text=f"セリフ{i}") for i in range(15)
            ],
            thumbnail_title="Pydantic最強",
            description="テスト概要"
        )
        print(f"[OK] 正常なScript作成成功")
        print(f"  タイトル: {script.title}")
        print(f"  総ターン数: {script.total_turns}")
        print(f"  テーマ: {script.theme}")
    except Exception as e:
        print(f"[FAIL] エラー: {e}")
    
    # 最低ターン数制約のテスト（10ターン未満で失敗するはず）
    try:
        script_short = Script(
            title="短い台本",
            theme="テスト",
            sections=[
                DialogueLine(speaker="A", text="短い")
            ]
        )
        print(f"[FAIL] 最低ターン数制約が機能していない: {script_short.total_turns}")
    except ValidationError as e:
        print(f"[OK] 最低ターン数制約が正しく機能: {e.error_count()} errors")
    
    # 後方互換性テスト（dialogueフィールド）
    try:
        json_data = {
            "title": "互換性テスト",
            "theme": "後方互換",
            "dialogue": [
                {"speaker": "A", "text": f"互換性テスト{i}"} for i in range(12)
            ],
            "description": "テスト"
        }
        script_compat = Script(**json_data)
        print(f"[OK] 後方互換性OK: dialogue -> sections変換成功")
        print(f"  総ターン数: {script_compat.total_turns}")
        print(f"  dialogueプロパティ: {len(script_compat.dialogue)} items")
    except Exception as e:
        print(f"[FAIL] 後方互換性エラー: {e}")


def test_research_result():
    """ResearchResultモデルのテスト"""
    print("\n=== ResearchResult モデルテスト ===")
    
    # 正常なケース
    try:
        result = ResearchResult(
            query="Pydanticとは",
            raw_content="Pydanticはデータバリデーションライブラリです。",
            sources=[
                ResearchSource(
                    title="Pydantic公式ドキュメント",
                    url="https://docs.pydantic.dev/",
                    snippet="Data validation using Python type hints"
                )
            ],
            timestamp="2026-02-05T23:00:00",
            provider="perplexity"
        )
        print(f"[OK] 正常なResearchResult作成成功")
        print(f"  クエリ: {result.query}")
        print(f"  ソース数: {len(result.sources)}")
    except Exception as e:
        print(f"[FAIL] エラー: {e}")
    
    # 後方互換性テスト（content → raw_content）
    try:
        result_compat = ResearchResult(
            content="後方互換性テスト",
            mode="trivia"
        )
        print(f"[OK] 後方互換性OK: content -> raw_content変換成功")
        print(f"  raw_content: {result_compat.raw_content[:30]}...")
        print(f"  query: {result_compat.query}")
    except Exception as e:
        print(f"[FAIL] 後方互換性エラー: {e}")


def test_model_dump():
    """model_dump()による辞書変換テスト（既存パイプライン互換性）"""
    print("\n=== model_dump() 互換性テスト ===")
    
    try:
        script = Script(
            title="辞書変換テスト",
            theme="互換性",
            sections=[
                DialogueLine(speaker="A", text=f"テスト{i}") for i in range(10)
            ],
            description="テスト概要"
        )
        
        # 辞書に変換
        script_dict = script.model_dump()
        
        print(f"[OK] model_dump()成功")
        print(f"  型: {type(script_dict)}")
        print(f"  キー: {list(script_dict.keys())}")
        print(f"  sections数: {len(script_dict['sections'])}")
        
        # JSONシリアライズ可能か確認
        json_str = json.dumps(script_dict, ensure_ascii=False, indent=2)
        print(f"[OK] JSONシリアライズ成功: {len(json_str)} bytes")
        
    except Exception as e:
        print(f"[FAIL] エラー: {e}")


def test_json_roundtrip():
    """JSON往復変換テスト"""
    print("\n=== JSON往復変換テスト ===")
    
    try:
        # オリジナルのScriptオブジェクト
        original = Script(
            title="往復テスト",
            theme="JSON変換",
            sections=[
                DialogueLine(speaker="A", text="こんにちは", emotion="joy"),
                DialogueLine(speaker="B", text="こんにちは", emotion="neutral"),
                DialogueLine(speaker="A", text="元気ですか？"),
                DialogueLine(speaker="B", text="元気です！", emotion="joy"),
                DialogueLine(speaker="A", text="それは良かった"),
                DialogueLine(speaker="B", text="ありがとう"),
                DialogueLine(speaker="A", text="また話しましょう"),
                DialogueLine(speaker="B", text="はい"),
                DialogueLine(speaker="A", text="さようなら"),
                DialogueLine(speaker="B", text="さようなら", emotion="neutral"),
            ],
            thumbnail_title="往復テスト",
            description="JSON往復変換のテスト"
        )
        
        # 辞書に変換
        dict_data = original.model_dump()
        
        # JSONに変換
        json_str = json.dumps(dict_data, ensure_ascii=False)
        
        # JSONから辞書に戻す
        dict_restored = json.loads(json_str)
        
        # 辞書からScriptオブジェクトに戻す
        restored = Script(**dict_restored)
        
        print(f"[OK] JSON往復変換成功")
        print(f"  オリジナル: {original.title} ({original.total_turns} turns)")
        print(f"  復元後: {restored.title} ({restored.total_turns} turns)")
        print(f"  一致: {original.title == restored.title and original.total_turns == restored.total_turns}")
        
    except Exception as e:
        print(f"[FAIL] エラー: {e}")


def main():
    """全テストを実行"""
    print("=" * 60)
    print("Pydantic モデル検証テスト")
    print("=" * 60)
    
    test_dialogue_line()
    test_script_model()
    test_research_result()
    test_model_dump()
    test_json_roundtrip()
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
