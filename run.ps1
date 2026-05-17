$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Get-PythonCommand {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @("py", "-3") }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @("python") }

    throw "Python was not found. Install Python 3.10+ or add it to PATH."
}

function Invoke-Python {
    param(
        [string[]]$PythonCommand,
        [string[]]$Arguments
    )

    $exe = $PythonCommand[0]
    $prefixArgs = @()
    if ($PythonCommand.Length -gt 1) {
        $prefixArgs = $PythonCommand[1..($PythonCommand.Length - 1)]
    }
    & $exe @prefixArgs @Arguments
}

$Python = Get-PythonCommand
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment: .venv"
    Invoke-Python -PythonCommand $Python -Arguments @("-m", "venv", ".venv")
}

Write-Host "Installing/updating dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt

Write-Host ""
Write-Host "Local web page: http://localhost:8000"
Write-Host "The first transcription may download the selected Whisper model."
Write-Host ""

& $VenvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
