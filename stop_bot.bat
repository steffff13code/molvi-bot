@echo off
echo Stopping MOLVI bot...
taskkill /F /IM pythonw.exe >nul 2>&1
echo Done.
timeout /t 2 >nul
