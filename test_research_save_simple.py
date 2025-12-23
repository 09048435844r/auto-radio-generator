"""research.json保存の簡易テスト"""
import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from workflow import UIOverrides, generate_video_workflow
from core.models.config import load_config

async def test_research_save():
    """リサーチ保存のテスト"""
    print("="*60)
    print("research.json保存テスト開始")
    print("="*60)
    
    # 設定を読み込み
    config = load_config()
    
    # UIオーバーライド設定
    overrides = UIOverrides(
        research_mode="weekly_digest",  # 今週のまとめモード
        enable_research=True
    )
    
    print(f"\n設定確認:")
    print(f"  enable_research: {overrides.enable_research}")
    print(f"  research_mode: {overrides.research_mode}")
    print(f"  条件チェック: {overrides.enable_research and overrides.research_mode}")
    
    # テーマ
    theme = "最新のAI技術"
    
    print(f"\nテーマ: {theme}")
    print(f"\nワークフロー実行中...")
    
    try:
        # ワークフローを実行
        result = await generate_video_workflow(
            theme=theme,
            config=config,
            overrides=overrides,
            progress=lambda p, msg: print(f"  進捗 {int(p*100)}%: {msg}"),
            log=lambda msg: print(f"  [LOG] {msg}")
        )
        
        print(f"\n✓ ワークフロー完了")
        print(f"  動画パス: {result.video_path}")
        
        # research.jsonの存在確認
        output_dir = result.video_path.parent.parent
        research_json = output_dir / "research.json"
        
        print(f"\n出力ディレクトリ: {output_dir}")
        print(f"research.json 存在: {research_json.exists()}")
        
        if research_json.exists():
            print(f"✓ research.json が正常に保存されました")
            print(f"  サイズ: {research_json.stat().st_size} bytes")
        else:
            print(f"✗ research.json が保存されていません")
            
    except Exception as e:
        print(f"\n✗ エラー発生: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_research_save())
