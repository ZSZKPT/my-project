@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -c "import sys; assert sys.version_info >= (3,12), '需要 Python 3.12+'"
  if errorlevel 1 goto failed
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import shapely, PIL, svgelements" 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements.lock
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip check
if errorlevel 1 goto failed
echo 浏览器打开 http://127.0.0.1:8765 ，按 Ctrl+C 退出。
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe server.py --port 8765
goto end
:failed
echo 启动失败。请安装 Python 3.12 或更高版本，并检查上方错误。
pause
:end
