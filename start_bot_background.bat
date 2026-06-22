@echo off
cd /d "%~dp0"
start "" /b ".venv\Scripts\pythonw.exe" -m bot
echo MOLVI bot started in background. Logs: logs\molvi.log
echo To stop: run stop_bot.bat
timeout /t 3 >nul
