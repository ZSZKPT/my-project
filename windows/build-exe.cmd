@echo off
cd /d "%~dp0\.."
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r desktop\requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name MiaoshouTemuTool --paths . --add-data "desktop/assets;assets" desktop\main.py
if errorlevel 1 goto fail
powershell.exe -NoProfile -Command "Compress-Archive -Path dist\MiaoshouTemuTool.exe,desktop\README.md -DestinationPath dist\MiaoshouTemuTool-Windows.zip -Force"
if errorlevel 1 goto fail
echo EXE created: dist\MiaoshouTemuTool.exe
pause
exit /b 0
:fail
echo Build failed. Review the message above.
pause
exit /b 1
