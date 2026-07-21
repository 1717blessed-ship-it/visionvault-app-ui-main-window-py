param([switch]$RunUI)

$ErrorActionPreference = 'Stop'
Write-Host "Running unit tests (pytest)..."
python -m pytest -q
$pytestCode = $LASTEXITCODE
Write-Host "pytest exit code: $pytestCode"

Write-Host "Running verification script..."
python tools/verify_selection.py

if ($RunUI) {
    Write-Host "Starting the application (main.py) in a new process..."
    Start-Process -NoNewWindow -FilePath python -ArgumentList "main.py"
}

if ($pytestCode -ne 0) { exit $pytestCode } else { exit 0 }
