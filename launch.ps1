$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8000"

Start-Job -ScriptBlock {
    param($TargetUrl)

    for ($i = 0; $i -lt 120; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $TargetUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Start-Process $TargetUrl
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
} -ArgumentList $Url | Out-Null

& (Join-Path $Root "run.ps1")
