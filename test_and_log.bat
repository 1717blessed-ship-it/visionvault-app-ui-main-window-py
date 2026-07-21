@echo off
echo Limpiando cache de Python...
if exist app\__pycache__ rd /s /q app\__pycache__
if exist app\stickers\__pycache__ rd /s /q app\stickers\__pycache__
if exist app\ui\__pycache__ rd /s /q app\ui\__pycache__
if exist app\database\__pycache__ rd /s /q app\database\__pycache__

echo.
echo Ejecutando test...
python force_test_studio.py

echo.
echo Mostrando resultado:
if exist force_test_output.txt (
    type force_test_output.txt
) else (
    echo ERROR: No se creo el archivo force_test_output.txt
)

pause
