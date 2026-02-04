#!/usr/bin/env python3
"""
静的解析と単体テストスクリプト
APIを叩かずに、インポートとクラス初期化が正常に動作するかを検証します。
"""
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("=== 依存関係チェック開始 ===")
print("=" * 60)

errors = []

# 1. 重要なモジュールのインポートテスト
print("\n[1/5] Checking core module imports...")
try:
    from core.models import load_config, Script, AppConfig
    from core.interfaces import IScriptGenerator, ResearchMode
    from core.settings_manager import SettingsManager
    from core.prompt_manager import PromptManager
    print("[OK] Core modules import: OK")
except Exception as e:
    errors.append(f"Core modules import failed: {e}")
    print(f"[FAILED] Core modules import: FAILED - {e}")

# 2. サービスモジュールのインポートテスト
print("\n[2/5] Checking service module imports...")
try:
    from services.script_generation import GeminiClient
    from services.research import PerplexityResearcher
    from services.audio_synthesis import VoicevoxClient
    from services.video_rendering import FfmpegRenderer
    print("[OK] Service modules import: OK")
except Exception as e:
    errors.append(f"Service modules import failed: {e}")
    print(f"[FAILED] Service modules import: FAILED - {e}")

# 3. GeminiClientの初期化テスト（config引数必須）
print("\n[3/5] Checking GeminiClient initialization...")
try:
    from services.script_generation.gemini_client import GeminiClient
    from core.models.config import AppConfig, YamlConfig, EnvSettings
    
    # モックConfigを作成
    mock_env = EnvSettings(
        gemini_api_key="test_key",
        perplexity_api_key="test_key",
        voicevox_url="http://localhost:50021"
    )
    mock_yaml = YamlConfig()
    mock_config = AppConfig(
        env=mock_env,
        yaml=mock_yaml,
        project_root=PROJECT_ROOT
    )
    
    # GeminiClientを初期化（config引数を渡す）
    client = GeminiClient(mock_config)
    print("[OK] GeminiClient initialization with config: OK")
except Exception as e:
    errors.append(f"GeminiClient initialization failed: {e}")
    print(f"[FAILED] GeminiClient initialization: FAILED - {e}")

# 4. SettingsManagerのメソッドテスト
print("\n[4/5] Checking SettingsManager methods...")
try:
    from core.settings_manager import SettingsManager
    
    settings_manager = SettingsManager()
    
    # load()メソッドが存在するか確認
    if not hasattr(settings_manager, 'load'):
        raise AttributeError("SettingsManager does not have 'load' method")
    
    # load()を呼び出し（ファイルがなくてもデフォルト値を返すはず）
    user_settings = settings_manager.load()
    print("[OK] SettingsManager.load() method: OK")
except Exception as e:
    errors.append(f"SettingsManager method check failed: {e}")
    print(f"[FAILED] SettingsManager method: FAILED - {e}")

# 5. workflow.pyの重要なインポートテスト
print("\n[5/5] Checking workflow.py imports...")
try:
    # workflow.pyで使用されている重要なインポートを確認
    from core.models.config import load_config
    from core.settings_manager import SettingsManager
    
    # load_config()が呼び出せるか確認
    config = load_config()
    print("[OK] workflow.py critical imports: OK")
except Exception as e:
    errors.append(f"workflow.py imports failed: {e}")
    print(f"[FAILED] workflow.py imports: FAILED - {e}")

# 結果サマリー
print("\n" + "=" * 60)
if errors:
    print("[ERROR] エラー検出: 以下の問題を修正してください")
    print("=" * 60)
    for i, error in enumerate(errors, 1):
        print(f"{i}. {error}")
    sys.exit(1)
else:
    print("[SUCCESS] 全チェック合格！修正は完了しています")
    print("=" * 60)
    print("\n次のステップ:")
    print("1. git add verify_fix.py")
    print("2. git commit -m 'test: Add integration verification script'")
    print("3. app.py を実行して実際の動作を確認")
    sys.exit(0)
