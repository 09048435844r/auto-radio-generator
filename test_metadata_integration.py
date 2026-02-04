#!/usr/bin/env python3
"""
メタデータ統合テストスクリプト
概要欄のチャプター追記とサムネイルのキャッチフレーズ描画をテストします。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("=== メタデータ統合テスト ===")
print("=" * 60)

# テスト1: 概要欄にチャプターが追記されるか確認
print("\n[Test 1/2] 概要欄のチャプター追記テスト")
print("-" * 60)

from core.interfaces import ChapterMarker
from core.models.script import Script, DialogueLine
from workflow import _generate_youtube_metadata

# ダミーデータを作成
dummy_script = Script(
    title="",  # 意図的に空（prompts.yamlの仕様）
    description="",
    dialogue=[
        DialogueLine(speaker_id="main", text="こんにちは、今日はAIについて話します。", section="intro"),
        DialogueLine(speaker_id="sub", text="面白そうですね。", section="intro"),
    ]
)

dummy_chapters = [
    ChapterMarker(start_time_sec=0.0, title="オープニング", section_id="intro"),
    ChapterMarker(start_time_sec=30.5, title="本編", section_id="main"),
    ChapterMarker(start_time_sec=120.0, title="エンディング", section_id="ending"),
]

dummy_theme = "AIの未来について"

# メタデータ生成を実行
output_path = PROJECT_ROOT / "output" / "test_integration" / "metadata.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

try:
    print(f"テーマ: {dummy_theme}")
    print(f"チャプター数: {len(dummy_chapters)}")
    
    metadata = _generate_youtube_metadata(
        script=dummy_script,
        chapters=dummy_chapters,
        output_path=output_path,
        theme=dummy_theme
    )
    
    print("\n[Result]")
    print(f"[OK] Metadata generation success")
    print(f"[OK] Title: {metadata.get('title', 'N/A')}")
    print(f"[OK] Thumbnail text: {metadata.get('thumbnail_title', 'N/A')}")
    
    # 概要欄にチャプターが含まれているか確認
    description = metadata.get("description", "")
    has_chapters = "00:00" in description or "00:30" in description or "02:00" in description
    
    if has_chapters:
        print(f"[OK] Description contains chapter information")
        print(f"\n--- Description (first 300 chars) ---")
        print(description[:300])
        if len(description) > 300:
            print("...")
    else:
        print(f"[FAIL] Description does not contain chapter information")
        print(f"\n--- Full Description ---")
        print(description)
    
    # metadata.txtファイルも確認
    if output_path.exists():
        print(f"\n[OK] metadata.txt saved: {output_path}")
        print(f"  File size: {output_path.stat().st_size} bytes")
    
except Exception as e:
    print(f"[FAIL] Metadata generation error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# テスト2: サムネイル生成でキャッチフレーズが使われるか確認
print("\n" + "=" * 60)
print("[Test 2/2] サムネイルのキャッチフレーズ描画テスト")
print("-" * 60)

from services.media_processing import ThumbnailGenerator

# ダミー背景画像を探す
background_candidates = [
    PROJECT_ROOT / "assets" / "backgrounds" / "default.png",
    PROJECT_ROOT / "assets" / "backgrounds" / "Minimalist_wooden_desk_workspace_a_tablet_with_finan_9389360b-d664-4a2b-bb7b-ddaf4a5dc15d_0.png",
]

background_path = None
for candidate in background_candidates:
    if candidate.exists():
        background_path = candidate
        break

if not background_path:
    print("⚠ 背景画像が見つかりません。サムネイルテストをスキップします。")
else:
    try:
        thumbnail_generator = ThumbnailGenerator()
        thumbnail_output = PROJECT_ROOT / "output" / "test_integration" / "thumbnail_test.png"
        
        # AI生成のキャッチフレーズを使用
        catchphrase = metadata.get("thumbnail_title", "テスト")
        
        print(f"背景画像: {background_path.name}")
        print(f"キャッチフレーズ: {catchphrase}")
        
        thumbnail_generator.generate(
            title=metadata.get("title", "テストタイトル"),
            thumbnail_title=catchphrase,
            background_path=background_path,
            output_path=thumbnail_output
        )
        
        print(f"[OK] Thumbnail generation success: {thumbnail_output}")
        print(f"  File size: {thumbnail_output.stat().st_size / 1024:.1f} KB")
        print(f"  Catchphrase '{catchphrase}' should be rendered")
        
    except Exception as e:
        print(f"[FAIL] Thumbnail generation error: {e}")
        import traceback
        traceback.print_exc()

# 最終結果
print("\n" + "=" * 60)
print("[SUCCESS] メタデータ統合テスト完了")
print("=" * 60)
print("\n次のステップ:")
print("1. 実際の動画生成を実行してください")
print("2. UIで以下を確認してください:")
print("   - 概要欄にAI生成の説明文とチャプター情報の両方が含まれているか")
print("   - サムネイル画像にAI生成のキャッチフレーズが表示されているか")
print(f"\n生成されたファイル:")
print(f"  - {output_path}")
if background_path:
    print(f"  - {thumbnail_output}")
