# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Test dashboard functions
def test_dashboard():
    print("Testing Dashboard functions...")
    
    # Create test data
    test_exec_data = [
        {
            "execution_id": "test-001",
            "timestamp": datetime.now().isoformat(),
            "theme": "Test Theme 1",
            "execution_time_seconds": 120.5,
            "success": True
        }
    ]
    
    test_cost_data = [
        {
            "execution_id": "test-001",
            "timestamp": datetime.now().isoformat(),
            "total_cost_usd": 0.0250,
            "perplexity_cost_usd": 0.0100,
            "gemini_cost_usd": 0.0150,
            "voicevox_cost_usd": 0.0000
        }
    ]
    
    # Create logs directory
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # Write test data
    month = datetime.now().strftime("%Y-%m")
    with open(logs_dir / f"execution_record_{month}.jsonl", 'w', encoding='utf-8') as f:
        for item in test_exec_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    with open(logs_dir / f"cost_history_{month}.jsonl", 'w', encoding='utf-8') as f:
        for item in test_cost_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"Created test data for month: {month}")
    print("Dashboard test completed successfully!")

if __name__ == "__main__":
    test_dashboard()
