@echo off
echo ==========================================================
echo   Launching LLM by norin (RTX 4070 Ti Local LLM Assistant)
echo ==========================================================

start "LLM Backend" cmd /k "cd /d %~dp0backend && call run_backend.bat"
start "LLM Frontend" cmd /k "cd /d %~dp0frontend && call run_frontend.bat"

echo Waiting 3 seconds for services to initialize...
timeout /t 3 /nobreak >nul
start http://localhost:5173
echo App launched in default browser!
