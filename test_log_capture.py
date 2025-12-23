"""ログ出力をキャプチャしてresearch.json保存処理を確認"""
import asyncio
import sys
from pathlib import Path
from io import StringIO

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from workflow import UIOverrides, generate_video_workflow
from core.models.config import load_config

# ログをキャプチャ
captured_logs = []

def capture_log(msg: str):
    """ログをキャプチャ"""
    captured_logs.append(msg)
    print(msg)

async def test_with_log_capture():
    """ログをキャプチャしながらテスト実行"""
    print("="*60)
    print("research.json保存デバッグ - ログキャプチャモード")
    print("="*60)
    
    # 設定を読み込み
    config = load_config()
    
    # UIオーバーライド設定（weekly_digestモードでテスト）
    overrides = UIOverrides(
        research_mode="weekly_digest",
        enable_research=True
    )
    
    print(f"\n設定:")
    print(f"  enable_research: {overrides.enable_research}")
    print(f"  research_mode: {overrides.research_mode}")
    
    theme = "最新のAI技術"
    print(f"  テーマ: {theme}")
    print(f"\nワークフロー実行中...\n")
    
    try:
        result = await generate_video_workflow(
            theme=theme,
            config=config,
            overrides=overrides,
            progress=lambda p, msg: None,  # 進捗は無視
            log=capture_log  # ログをキャプチャ
        )
        
        print("\n" + "="*60)
        print("実行完了 - ログ分析")
        print("="*60)
        
        # ログからDEBUGメッセージを探す
        debug_logs = [log for log in captured_logs if "[DEBUG]" in log]
        research_logs = [log for log in captured_logs if "リサーチ" in log or "research" in log.lower()]
        error_logs = [log for log in captured_logs if "エラー" in log or "error" in log.lower()]
        
        print(f"\n総ログ数: {len(captured_logs)}")
        print(f"DEBUGログ数: {len(debug_logs)}")
        print(f"リサーチ関連ログ数: {len(research_logs)}")
        print(f"エラーログ数: {len(error_logs)}")
        
        if debug_logs:
            print("\n[DEBUG]ログ:")
            for log in debug_logs:
                print(f"  {log}")
        
        if research_logs:
            print("\nリサーチ関連ログ:")
            for log in research_logs[:10]:  # 最初の10件のみ
                print(f"  {log}")
        
        if error_logs:
            print("\nエラーログ:")
            for log in error_logs:
                print(f"  {log}")
        
        # research.jsonの存在確認
        output_dir = result.video_path.parent.parent
        research_json = output_dir / "research.json"
        
        print(f"\n出力ディレクトリ: {output_dir}")
        print(f"research.json 存在: {research_json.exists()}")
        
        if not research_json.exists():
            print("\n原因分析:")
            if not debug_logs:
                print("  ✗ [DEBUG]ログが出力されていない → 保存処理が実行されていない")
            if not any("リサーチ完了" in log for log in research_logs):
                print("  ✗ リサーチが完了していない")
            if error_logs:
                print("  ✗ エラーが発生している")
        
    except Exception as e:
        print(f"\n✗ エラー発生: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_with_log_capture())
