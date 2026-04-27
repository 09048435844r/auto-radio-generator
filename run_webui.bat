@echo off
chcp 65001 > nul
echo ========================================
echo   自動ラジオ動画生成システム - Web UI
echo ========================================
echo.
echo ブラウザで http://127.0.0.1:7860 を開きます...
echo.
python app.py
pause
