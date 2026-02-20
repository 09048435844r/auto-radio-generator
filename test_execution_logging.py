"""実行ログ・コスト履歴のテストスクリプト

Mockモードで動画生成を実行し、生成されたJSONLファイルを検証する。
"""
import json
import sys
from pathlib import Path
from workflow import run_workflow_sync, UIOverrides

# Windows console encoding fix
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def test_execution_logging():
    """実行ログとコスト履歴の記録をテスト"""
    print("=" * 60)
    print("実行ログ・コスト履歴テスト開始")
    print("=" * 60)
    
    # Mockモードで動画生成を実行
    print("\n[1] Mockモードで動画生成を実行中...")
    
    overrides = UIOverrides(
        research_mode="trivia",
        enable_research=True,
        bgm_file="【万能型】おしゃれなLo-Fi Hip Hop.mp3"
    )
    
    result = run_workflow_sync(
        theme="テスト用テーマ：実行ログ検証",
        overrides=overrides,
        use_mock=True,
        log_callback=lambda msg: print(f"  {msg}")
    )
    
    if not result.success:
        print(f"\n❌ 動画生成失敗: {result.error_message}")
        return False
    
    print(f"\n✓ 動画生成成功")
    
    # ログディレクトリを確認
    print("\n[2] ログファイルを確認中...")
    logs_dir = Path(__file__).parent / "logs"
    
    if not logs_dir.exists():
        print(f"❌ ログディレクトリが存在しません: {logs_dir}")
        return False
    
    print(f"✓ ログディレクトリ存在: {logs_dir}")
    
    # 月次ファイル名を生成
    from datetime import datetime
    year_month = datetime.now().strftime("%Y-%m")
    
    execution_log_file = logs_dir / f"execution_record_{year_month}.jsonl"
    cost_log_file = logs_dir / f"cost_history_{year_month}.jsonl"
    
    # execution_record.jsonlを確認
    print(f"\n[3] execution_record_{year_month}.jsonl を確認中...")
    
    if not execution_log_file.exists():
        print(f"❌ 実行ログファイルが存在しません: {execution_log_file}")
        return False
    
    print(f"✓ ファイル存在: {execution_log_file}")
    
    # 最後の行を読み込み
    with open(execution_log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    if not lines:
        print("❌ 実行ログファイルが空です")
        return False
    
    last_line = lines[-1].strip()
    execution_entry = json.loads(last_line)
    
    print(f"\n✓ 実行ログエントリ読み込み成功")
    print(f"  execution_id: {execution_entry.get('execution_id')}")
    print(f"  app_version: {execution_entry.get('app_version')}")
    print(f"  theme: {execution_entry.get('theme')}")
    print(f"  success: {execution_entry.get('success')}")
    print(f"  prompts count: {len(execution_entry.get('prompts', []))}")
    print(f"  generated_files: {list(execution_entry.get('generated_files', {}).keys())}")
    
    # 必須フィールドを検証
    required_fields = [
        'execution_id', 'app_version', 'timestamp', 'output_directory',
        'theme', 'config_snapshot', 'prompts', 'generated_files',
        'success', 'total_duration_sec'
    ]
    
    missing_fields = [f for f in required_fields if f not in execution_entry]
    if missing_fields:
        print(f"\n❌ 必須フィールドが欠けています: {missing_fields}")
        return False
    
    print(f"\n✓ 全必須フィールド存在")
    
    # cost_history.jsonlを確認
    print(f"\n[4] cost_history_{year_month}.jsonl を確認中...")
    
    if not cost_log_file.exists():
        print(f"❌ コスト履歴ファイルが存在しません: {cost_log_file}")
        return False
    
    print(f"✓ ファイル存在: {cost_log_file}")
    
    # 最後の行を読み込み
    with open(cost_log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    if not lines:
        print("❌ コスト履歴ファイルが空です")
        return False
    
    last_line = lines[-1].strip()
    cost_entry = json.loads(last_line)
    
    print(f"\n✓ コストログエントリ読み込み成功")
    print(f"  execution_id: {cost_entry.get('execution_id')}")
    print(f"  gemini_model_name: {cost_entry.get('gemini_model_name')}")
    print(f"  gemini_input_tokens: {cost_entry.get('gemini_input_tokens')}")
    print(f"  gemini_output_tokens: {cost_entry.get('gemini_output_tokens')}")
    print(f"  total_usd: ${cost_entry.get('total_usd', 0):.4f}")
    print(f"  total_duration_sec: {cost_entry.get('total_duration_sec', 0):.1f}秒")
    
    # execution_idが一致することを確認
    if execution_entry.get('execution_id') != cost_entry.get('execution_id'):
        print(f"\n❌ execution_idが一致しません")
        print(f"  execution_log: {execution_entry.get('execution_id')}")
        print(f"  cost_log: {cost_entry.get('execution_id')}")
        return False
    
    print(f"\n✓ execution_id一致")
    
    # プロンプト記録のサンプルを表示
    if execution_entry.get('prompts'):
        print(f"\n[5] プロンプト記録サンプル（最初の1件）:")
        first_prompt = execution_entry['prompts'][0]
        print(f"  phase: {first_prompt.get('phase')}")
        print(f"  api_provider: {first_prompt.get('api_provider')}")
        print(f"  model_name: {first_prompt.get('model_name')}")
        print(f"  user_prompt length: {len(first_prompt.get('user_prompt', ''))} chars")
        print(f"  raw_response length: {len(first_prompt.get('raw_response', ''))} chars")
    
    print("\n" + "=" * 60)
    print("✅ 全テスト合格！")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    success = test_execution_logging()
    exit(0 if success else 1)
