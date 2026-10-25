@echo off
chcp 65001 > nul
echo ========================================================
echo   Local GPU AI Discord Bot 起動スクリプト
echo ========================================================
cd /d "%~dp0backend"

if not exist ".env" (
    echo DISCORD_BOT_TOKEN=>> .env
)

.\.venv\Scripts\python discord_bot.py
pause
