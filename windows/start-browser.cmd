@echo off
cd /d "%~dp0\.."
powershell.exe -NoProfile -File "%~dp0start-browser.ps1"
pause
