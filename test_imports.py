# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import gradio as gr
    print("Gradio imported successfully")
    
    import pandas as pd
    print("Pandas imported successfully")
    
    import plotly.graph_objects as go
    print("Plotly.graph_objects imported successfully")
    
    import plotly.express as px
    print("Plotly.express imported successfully")
    
    from workflow import UIOverrides, run_workflow_sync, WorkflowResult, scan_assets, create_script_generator, load_config
    print("Workflow functions imported successfully")
    
    from core.models import Script
    print("Core models imported successfully")
    
    from core.interfaces import ResearchResult
    print("Core interfaces imported successfully")
    
    from core.settings_manager import SettingsManager
    print("Settings manager imported successfully")
    
    print("\nAll imports successful!")
    
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()
