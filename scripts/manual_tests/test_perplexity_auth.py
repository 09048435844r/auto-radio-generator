"""Perplexity API認証テスト"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import load_config
from openai import OpenAI

def test_perplexity_auth():
    """Perplexity API認証をテスト"""
    config = load_config()
    
    api_key = config.env.perplexity_api_key
    print(f"API Key length: {len(api_key) if api_key else 0} chars")
    print(f"API Key prefix: {api_key[:10]}..." if api_key else "No API key")
    
    if not api_key:
        print("❌ PERPLEXITY_API_KEY が設定されていません")
        return
    
    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        
        print("\n🔍 Perplexity API接続テスト中...")
        response = client.chat.completions.create(
            model="llama-3.1-sonar-small-128k-online",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=10
        )
        
        print("✅ 認証成功！")
        print(f"Response: {response}")
        
    except Exception as e:
        print(f"❌ 認証エラー: {e}")
        print(f"エラー型: {type(e).__name__}")
        
        error_str = str(e)
        if "401" in error_str or "Unauthorized" in error_str:
            print("\n【原因】APIキーが無効または期限切れです")
            print("【対処】")
            print("1. https://www.perplexity.ai/settings/api にアクセス")
            print("2. 新しいAPIキーを生成")
            print("3. .envファイルのPERPLEXITY_API_KEYを更新")
        elif "429" in error_str:
            print("\n【原因】レート制限に達しました")
        else:
            print(f"\n【詳細】{error_str}")

if __name__ == "__main__":
    test_perplexity_auth()
