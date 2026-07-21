@echo off
cd /d "%~dp0"
"C:\Python313\python.exe" "%~dp0main.py"
if errorlevel 1 (
    echo.
    echo Doccione no pudo iniciarse. Copiá este mensaje o revisá error_inicio_doccione.log.
    pause
)
