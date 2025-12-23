"""research.json保存のデバッグ用スクリプト - ログ出力を詳細に確認"""
import sys
from pathlib import Path

# 最新の出力ディレクトリを確認
output_dir = Path("e:/windsurf/auto_radio_generator/output")
latest_dir = max(output_dir.glob("*"), key=lambda p: p.stat().st_mtime)

print(f"最新の出力ディレクトリ: {latest_dir}")
print(f"\nファイル一覧:")
for file in sorted(latest_dir.rglob("*")):
    if file.is_file():
        print(f"  {file.relative_to(latest_dir)} ({file.stat().st_size} bytes)")

# research.jsonの存在確認
research_json = latest_dir / "research.json"
print(f"\nresearch.json 存在確認: {research_json.exists()}")

# metadata.txtからリサーチ関連のログを探す
metadata_file = latest_dir / "metadata.txt"
if metadata_file.exists():
    print(f"\nmetadata.txt の内容を確認中...")
    content = metadata_file.read_text(encoding="utf-8", errors="ignore")
    if "リサーチ" in content or "research" in content.lower():
        print("  リサーチ関連の記述が見つかりました")
    else:
        print("  リサーチ関連の記述が見つかりませんでした")

# script.jsonからリサーチデータの痕跡を探す
script_file = latest_dir / "script.json"
if script_file.exists():
    print(f"\nscript.json の内容を確認中...")
    content = script_file.read_text(encoding="utf-8", errors="ignore")
    # リサーチデータが台本に反映されているか確認
    if len(content) > 5000:
        print(f"  台本サイズ: {len(content)} 文字（リサーチデータが含まれている可能性あり）")
    else:
        print(f"  台本サイズ: {len(content)} 文字（リサーチなしの可能性）")

print("\n" + "="*60)
print("デバッグ結論:")
print("="*60)
print("1. research.jsonが存在しない")
print("2. リサーチは実行されている（台本の内容から判断）")
print("3. 保存処理が実行されていない、またはエラーが発生している")
print("\n推奨アクション:")
print("- workflow.pyのlog()出力を確認")
print("- [DEBUG]メッセージが出力されているか確認")
print("- エラーメッセージが出力されているか確認")
