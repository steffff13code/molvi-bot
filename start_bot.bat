@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting MOLVI bot (@molviai_bot)...
echo Closing window will stop the bot. Keep it open.
.venv\Scripts\python.exe -m bot
pause
