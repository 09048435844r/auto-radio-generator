#!/usr/bin/env python3
"""
メタデータ生成ロジック検証スクリプト
動画を生成せずに、タイトル・サムネイル文字・概要欄の生成だけをテストします。
"""
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("=== メタデータ生成ロジック検証 ===")
print("=" * 60)

errors = []

# 1. 必要なモジュールのインポート
print("\n[1/4] Importing required modules...")
try:
    from services.script_generation.gemini_client import GeminiClient
    from core.models.config import load_config, AppConfig
    from core.models.script import Script, DialogueLine
    from core.interfaces import ChapterMarker
    print("[OK] Modules imported successfully")
except Exception as e:
    errors.append(f"Module import failed: {e}")
    print(f"[FAILED] Module import: {e}")
    sys.exit(1)

# 2. 設定の読み込み
print("\n[2/4] Loading configuration...")
try:
    config = load_config()
    print("[OK] Configuration loaded")
except Exception as e:
    errors.append(f"Config loading failed: {e}")
    print(f"[FAILED] Config loading: {e}")
    sys.exit(1)

# 3. GeminiClientの初期化
print("\n[3/4] Initializing GeminiClient...")
try:
    gemini_client = GeminiClient(config)
    print("[OK] GeminiClient initialized")
except Exception as e:
    errors.append(f"GeminiClient initialization failed: {e}")
    print(f"[FAILED] GeminiClient initialization: {e}")
    sys.exit(1)

# 4. メタデータ生成テスト
print("\n[4/4] Testing metadata generation...")
try:
    # ダミーの台本データを作成
    dummy_script_summary = """
    今日はAI技術の最新動向についてお話しします。
    特に注目されているのが、大規模言語モデルの進化です。
    これらのモデルは、自然な対話を実現できるようになってきました。
    """
    
    theme = "AI技術の最新動向と未来"
    
    print(f"\nテーマ: {theme}")
    print(f"台本要約: {dummy_script_summary[:100]}...")
    
    # packagingプロンプトでメタデータを生成
    print("\n[INFO] Calling generate_packaging_prompt()...")
    metadata_result = gemini_client.generate_packaging_prompt(
        theme=theme,
        script_summary=dummy_script_summary
    )
    
    if not metadata_result:
        raise ValueError("generate_packaging_prompt returned empty result")
    
    print(f"[OK] Raw response received ({len(metadata_result)} chars)")
    print(f"\n--- Raw Response ---")
    print(metadata_result[:500])
    if len(metadata_result) > 500:
        print("...")
    print("--- End of Raw Response ---\n")
    
    # JSONをパース（マークダウンコードブロックを除去）
    import json
    import re
    
    # ```json ... ``` を除去
    json_text = metadata_result.strip()
    if json_text.startswith("```"):
        # コードブロックを除去
        json_text = re.sub(r'^```(?:json)?\s*\n', '', json_text)
        json_text = re.sub(r'\n```\s*$', '', json_text)
    
    metadata = json.loads(json_text)
    
    # 必須フィールドの確認
    required_fields = ["title", "thumbnail_title", "description"]
    missing_fields = [field for field in required_fields if field not in metadata]
    
    if missing_fields:
        raise ValueError(f"Missing required fields: {missing_fields}")
    
    print("[OK] Metadata JSON parsed successfully")
    print("\n" + "=" * 60)
    print("=== Generated Metadata ===")
    print("=" * 60)
    print(f"\n[Title] ({len(metadata['title'])} chars)")
    print(metadata['title'])
    print(f"\n[Thumbnail Title] ({len(metadata['thumbnail_title'])} chars)")
    print(metadata['thumbnail_title'])
    print(f"\n[Description] ({len(metadata['description'])} chars)")
    print(metadata['description'][:300])
    if len(metadata['description']) > 300:
        print("...")
    print("\n" + "=" * 60)
    
    # 検証結果
    validation_results = []
    
    # タイトルの長さチェック（32文字以内推奨）
    if len(metadata['title']) <= 32:
        validation_results.append("[OK] Title length is within recommended limit (32 chars)")
    else:
        validation_results.append(f"[WARNING] Title is too long ({len(metadata['title'])} chars, recommended: 32)")
    
    # サムネイル文字の長さチェック（7文字以内推奨）
    if len(metadata['thumbnail_title']) <= 7:
        validation_results.append("[OK] Thumbnail title length is within recommended limit (7 chars)")
    else:
        validation_results.append(f"[WARNING] Thumbnail title is too long ({len(metadata['thumbnail_title'])} chars, recommended: 7)")
    
    # 概要欄の長さチェック（最低100文字）
    if len(metadata['description']) >= 100:
        validation_results.append("[OK] Description has sufficient length")
    else:
        validation_results.append(f"[WARNING] Description is too short ({len(metadata['description'])} chars)")
    
    print("\n=== Validation Results ===")
    for result in validation_results:
        print(result)
    
    # video_metadata.jsonとして保存テスト
    print("\n=== Testing JSON file save ===")
    test_output_dir = PROJECT_ROOT / "output" / "test_metadata"
    test_output_dir.mkdir(parents=True, exist_ok=True)
    
    metadata_json_path = test_output_dir / "video_metadata.json"
    metadata_json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Metadata saved to: {metadata_json_path}")
    print(f"[OK] File size: {metadata_json_path.stat().st_size} bytes")
    
    # 保存したファイルを読み込んで確認
    loaded_metadata = json.loads(metadata_json_path.read_text(encoding="utf-8"))
    if loaded_metadata == metadata:
        print("[OK] Saved metadata can be loaded correctly")
    else:
        print("[WARNING] Loaded metadata differs from original")
    
except Exception as e:
    errors.append(f"Metadata generation test failed: {e}")
    print(f"[FAILED] Metadata generation: {e}")
    import traceback
    print("\n--- Traceback ---")
    print(traceback.format_exc())
    print("--- End of Traceback ---")
    sys.exit(1)

# 結果サマリー
print("\n" + "=" * 60)
if errors:
    print("[ERROR] Some tests failed:")
    print("=" * 60)
    for i, error in enumerate(errors, 1):
        print(f"{i}. {error}")
    sys.exit(1)
else:
    print("[SUCCESS] All metadata generation tests passed!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Run the full workflow (app.py) to verify integration")
    print("2. Check that video_metadata.json is created in output folder")
    print("3. Verify that generated title/description appear in UI")
    sys.exit(0)
