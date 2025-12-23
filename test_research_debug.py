"""research.json保存のデバッグスクリプト"""
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from workflow import UIOverrides

# 最新の出力ディレクトリを確認
output_dir = Path("e:/windsurf/auto_radio_generator/output")
latest_dir = max(output_dir.glob("*"), key=lambda p: p.stat().st_mtime)

print(f"最新の出力ディレクトリ: {latest_dir}")
print(f"\nファイル一覧:")
for file in sorted(latest_dir.rglob("*")):
    if file.is_file():
        print(f"  {file.relative_to(latest_dir)}")

# research.jsonの存在確認
research_json = latest_dir / "research.json"
if research_json.exists():
    print(f"\n✓ research.json が存在します")
    print(f"  サイズ: {research_json.stat().st_size} bytes")
else:
    print(f"\n✗ research.json が存在しません")
    
# UIOverridesの設定を確認
print(f"\n=== UIOverrides設定の確認 ===")
overrides = UIOverrides(
    research_mode="trivia",
    enable_research=True
)
print(f"enable_research: {overrides.enable_research}")
print(f"research_mode: {overrides.research_mode}")
print(f"条件チェック: {overrides.enable_research and overrides.research_mode}")
