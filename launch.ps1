param(
    [int]$Port = 0,
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

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
$ExpectedApiVersion = 2
$existing = $null

try {
    $existing = Invoke-RestMethod -Uri $StatusUrl -TimeoutSec 2
    if ($null -ne $existing.status -and $existing.api_version -eq $ExpectedApiVersion) {
        Write-Host "Local Video Transcriber is already running: $Url"
        Start-Process $Url
        return
    }
} catch {
}

if ($null -ne $existing.status) {
    Write-Host "An older Local Video Transcriber backend is running. Restarting it before opening the page."
}

Start-Job -ScriptBlock {
    param($TargetUrl, $TargetStatusUrl, $RequiredApiVersion)

    for ($i = 0; $i -lt 120; $i++) {
        try {
            $status = Invoke-RestMethod -Uri $TargetStatusUrl -TimeoutSec 2
            if ($status.api_version -eq $RequiredApiVersion) {
                Start-Process $TargetUrl
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
} -ArgumentList $Url, $StatusUrl, $ExpectedApiVersion | Out-Null

& (Join-Path $Root "run.ps1") -Port $Port -InstallDeps:$InstallDeps
