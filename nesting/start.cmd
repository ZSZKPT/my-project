@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Buxu Nesting - Startup
set "PYTHONUTF8=1"
echo Buxu nesting startup. Keep this window open.
echo.
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 windows_bootstrap.py
goto finished
:use_python
where python >nul 2>nul
if errorlevel 1 goto missing_python
python windows_bootstrap.py
goto finished
:missing_python
echo Python was not found. Install Python 3.12 or newer first.
echo https://www.python.org/downloads/windows/
echo Enable "Add python.exe to PATH" during installation.
:finished
echo.
echo If startup failed, send a screenshot or startup.log from this folder.
echo Press any key to close this window.
pause >nul
