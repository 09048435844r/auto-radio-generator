# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import generate_video
import gradio as gr

def test_mock_mode():
    """Test Mock mode functionality"""
    print("Testing Mock mode...")
    
    try:
        # Test parameters
        test_params = {
            "theme": "AIの未来について",
            "research_mode": "トリビア (雑学)",
            "background_image": "default.png",
            "bgm_file": "default.mp3",
            "bgm_volume": 0.1,
            "fade_time": 3.0,
            "speed_scale": 1.0,
            "enable_spectrum": True,
            "use_mock": True,  # Enable Mock mode
            "avoid_topics": "",
            "upload_to_youtube": False,
            "footer_text": "",
            "progress": gr.Progress()
        }
        
        # Run generate_video with Mock mode
        result = generate_video(**test_params)
        
        video_path, log_output, cost_report, title, description, youtube_status = result
        
        print("\n--- Mock Mode Test Results ---")
        print(f"Video Path: {video_path}")
        print(f"Log Output (first 200 chars): {log_output[:200]}...")
        print(f"Cost Report: {cost_report}")
        print(f"Title: {title}")
        print(f"YouTube Status: {youtube_status}")
        
        # Check if Mock mode worked
        if "Mock" in log_output or "テスト" in log_output:
            print("\n✅ Mock mode is working correctly!")
        else:
            print("\n⚠️ Mock mode may not be working as expected")
            
        return True
        
    except Exception as e:
        print(f"\n❌ Error testing Mock mode: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_mock_mode()
    if success:
        print("\nMock mode test completed!")
    else:
        print("\nMock mode test failed!")
