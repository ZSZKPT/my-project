@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r desktop\requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name "飞凡上架" --paths . --add-data "desktop/assets;assets" desktop\main.py
if errorlevel 1 goto fail
powershell.exe -NoProfile -Command "Compress-Archive -Path dist\飞凡上架.exe,desktop\README.md -DestinationPath dist\飞凡上架-Windows.zip -Force"
if errorlevel 1 goto fail
echo EXE created: dist\飞凡上架.exe
pause
exit /b 0
:fail
echo Build failed. Review the message above.
pause
exit /b 1
