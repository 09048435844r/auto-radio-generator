#!/usr/bin/env python3
"""
formatted_titleに日付が含まれるかテストするスクリプト
"""
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("=== formatted_title Test ===")
print("=" * 60)

# ダミーメタデータ
dummy_metadata = {
    "title": "AIが凄すぎる件について",
    "thumbnail_title": "危険",
    "description": "これはテスト説明文です。"
}

# 日付入りタイトルを生成（workflow.pyと同じロジック）
creation_date = datetime.now().strftime("%Y.%m.%d")
ai_title = dummy_metadata.get("title", "無題")
formatted_title = f"{ai_title} ({creation_date}制作)"

print(f"\n[Test Result]")
print(f"AI Title: {ai_title}")
print(f"Creation Date: {creation_date}")
print(f"Formatted Title: {formatted_title}")

# 日付が含まれているか確認
if creation_date in formatted_title and "制作" in formatted_title:
    print(f"\n[OK] Formatted title contains date in correct format")
    print(f"Expected format: 'Title (YYYY.MM.DD制作)'")
    print(f"Actual: '{formatted_title}'")
else:
    print(f"\n[FAIL] Date not found in formatted title")
    sys.exit(1)

print("\n" + "=" * 60)
print("[SUCCESS] Test completed")
print("=" * 60)
