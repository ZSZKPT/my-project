$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3 is required. Install Python from python.org with the Python launcher.' }
}
& '.venv\Scripts\python.exe' -m pip install -r windows\requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.venv\Scripts\python.exe' windows\browser.py
if ($LASTEXITCODE -ne 0) { throw 'Browser startup failed.' }
