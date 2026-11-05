@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" /b "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b 0
)
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
) else (
    python "%~dp0main.py"
)
if errorlevel 1 (
    echo.
    echo Doccione no pudo iniciarse. Copiá este mensaje o revisá error_inicio_doccione.log.
    pause
)
