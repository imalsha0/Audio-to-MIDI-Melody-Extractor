$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv310\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Python 3.10 environment not found. Create .venv310 and install requirements.txt first."
}

$env:PYTHONPATH = Join-Path $projectRoot "backend"
& $python -m uvicorn main:app --host 127.0.0.1 --port 8000
