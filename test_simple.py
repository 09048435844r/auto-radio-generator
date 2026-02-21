# -*- coding: utf-8 -*-
"""Simple test to check if the app can run"""
import subprocess
import sys

print("Testing app startup...")

try:
    # Run app with --help to see if it can start
    result = subprocess.run(
        [sys.executable, "app.py", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd="e:\\windsurf\\auto_radio_generator"
    )
    
    if result.returncode == 0:
        print("App help displayed successfully")
        print(result.stdout[:500])
    else:
        print("App failed to start")
        print("Error:", result.stderr[:500])
        
except Exception as e:
    print(f"Error running app: {e}")
