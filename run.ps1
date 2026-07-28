param(
    [int]$Port = 0,
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($Port -eq 0) {
    if ($env:VIDEO_TRANSCRIBER_PORT) {
        $Port = [int]$env:VIDEO_TRANSCRIBER_PORT
    } else {
        $Port = 8876
    }
}

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}

$Url = "http://127.0.0.1:$Port"
$StatusUrl = "$Url/api/status"
$SpecUrl = "$Url/openapi.json"
$ExpectedApiVersion = 2
$existing = $null
$isProjectBackend = $false

try {
    $existing = Invoke-RestMethod -Uri $StatusUrl -TimeoutSec 2
    if ($null -ne $existing.status -and $existing.api_version -eq $ExpectedApiVersion) {
        Write-Host "Local Video Transcriber is already running: $Url"
        return
    }
} catch {
}

try {
    $spec = Invoke-RestMethod -Uri $SpecUrl -TimeoutSec 2
    $isProjectBackend = $spec.info.title -eq "Local Video Transcriber"
} catch {
}

$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $activeStatuses = @("queued", "running", "cancelling")
    $idleStatuses = @("idle", "done", "untranscribed", "error", "cancelled")
    if (-not $isProjectBackend) {
        throw "Port $Port is already in use, but the service could not be verified as Local Video Transcriber."
    }
    if ($null -ne $existing.status -and $activeStatuses -contains $existing.status) {
        throw "An older backend is still transcribing. Stop that task before restarting the application."
    }
    if ($null -eq $existing.status -or $idleStatuses -notcontains $existing.status) {
        throw "The outdated Local Video Transcriber backend did not report a known idle state, so it was not stopped."
    }

    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $expectedCommand = "*uvicorn app.main:app*--port $Port*"
    if ($listenerProcess.CommandLine -notlike $expectedCommand) {
        throw "Port $Port is already in use by another process ($($listener.OwningProcess))."
    }

    Write-Host "Stopping outdated backend process $($listener.OwningProcess)..."
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Milliseconds 500
}

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
$ShouldInstallDeps = [bool]$InstallDeps

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment: .venv"
    Invoke-Python -PythonCommand $Python -Arguments @("-m", "venv", ".venv")
    $ShouldInstallDeps = $true
}

if ($ShouldInstallDeps) {
    Write-Host "Installing/updating dependencies..."
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r requirements.txt
} else {
    Write-Host "Using existing virtual environment. Pass -InstallDeps to update dependencies."
}

Write-Host ""
Write-Host "Local web page: $Url"
Write-Host "The first transcription may download the selected Whisper model."
Write-Host ""

& $VenvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
