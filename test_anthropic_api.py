"""Anthropic API接続テストスクリプト"""
import os
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_anthropic_api():
    """Test Anthropic API connection and model availability"""
    
    # Check API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY が .env ファイルに設定されていません")
        return False
    
    print(f"[OK] API Key found: {api_key[:10]}...{api_key[-4:]}")
    
    # Initialize client
    try:
        client = Anthropic(api_key=api_key)
        print("[OK] Anthropic client initialized")
    except Exception as e:
        print(f"❌ Client initialization failed: {e}")
        return False
    
    # Test 1: List available models
    print("\n=== Available Models ===")
    try:
        response = client.models.list()
        if hasattr(response, 'data'):
            for model in response.data[:5]:  # Show first 5 models
                print(f"  - {model.id} ({model.display_name})")
        else:
            print("  No models found in response")
    except Exception as e:
        print(f"❌ Failed to list models: {e}")
    
    # Test 2: Try Claude Sonnet 4.6
    print("\n=== Testing claude-sonnet-4-6-20260205 ===")
    try:
        message = client.messages.create(
            model="claude-sonnet-4-6-20260205",
            max_tokens=100,
            messages=[
                {"role": "user", "content": "Hello, please respond with 'API test successful'"}
            ]
        )
        print(f"[OK] Model response: {message.content[0].text}")
        print(f"[OK] Usage: input={message.usage.input_tokens}, output={message.usage.output_tokens}")
        return True
    except Exception as e:
        print(f"❌ API call failed: {e}")
        
        # Test 3: Try alternative model names
        print("\n=== Trying alternative model names ===")
        alternative_models = [
            "claude-sonnet-4-6",
            "claude-sonnet-4-5-20250929",
            "claude-3-5-sonnet-20241022",
        ]
        
        for model_name in alternative_models:
            try:
                print(f"\nTrying: {model_name}")
                message = client.messages.create(
                    model=model_name,
                    max_tokens=50,
                    messages=[
                        {"role": "user", "content": "Test"}
                    ]
                )
                print(f"[OK] {model_name} works!")
                print(f"  Response: {message.content[0].text[:50]}...")
                return True
            except Exception as e:
                print(f"❌ {model_name} failed: {str(e)[:100]}")
        
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Anthropic API Connection Test")
    print("=" * 60)
    
    success = test_anthropic_api()
    
    print("\n" + "=" * 60)
    if success:
        print("[SUCCESS] API test completed successfully")
    else:
        print("❌ API test failed - please check your configuration")
    print("=" * 60)
