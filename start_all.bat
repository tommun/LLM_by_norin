@echo off
chcp 65001 > nul
echo ==========================================================
echo   🚀 LLM by norin & Discord Bot (ルカ) 一括起動スクリプト
echo   Target GPU: NVIDIA GeForce RTX 4070 Ti
echo ==========================================================

echo [1/3] バックエンド (FastAPI + Vision LLM) を起動中...
start "LLM Backend" cmd /k "cd /d %~dp0backend && call run_backend.bat"

echo [2/3] フロントエンド (Web UI) を起動中...
start "LLM Frontend" cmd /k "cd /d %~dp0frontend && call run_frontend.bat"

echo [3/3] Discord Bot (🎨 ルカ) を起動中...
start "Discord Bot Luka" cmd /k "cd /d %~dp0backend && call .\.venv\Scripts\activate && python discord_bot.py"

echo.
echo サービス初期化待機中 (約3秒)...
timeout /t 3 /nobreak >nul
start http://localhost:5173
echo ✅ すべてのサービスを起動しました！
pause
