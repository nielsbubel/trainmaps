[CmdletBinding()]
param([switch]$Staging, [switch]$HealthOnly)

$ErrorActionPreference = 'Stop'
if ($Staging -and $HealthOnly) { throw 'Staging und HealthOnly sind getrennte Betriebsarten.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$caddy = Join-Path $projectRoot '.local\tools\caddy-2.11.4\caddy.exe'
$stateFile = Join-Path $projectRoot '.local\https-process.json'

if (-not (Test-Path -LiteralPath $caddy)) {
    throw 'Caddy 2.11.4 fehlt in .local/tools/caddy-2.11.4. Siehe docs/HTTPS.md.'
}
if (Test-Path -LiteralPath $stateFile) {
    $previous = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $running = Get-Process -Id $previous.pid -ErrorAction SilentlyContinue
    if ($running -and $running.Path -eq $caddy -and
        $running.StartTime.ToUniversalTime() -eq ([datetime]$previous.started_at).ToUniversalTime()) {
        throw 'Der trainmaps-HTTPS-Prozess laeuft bereits. Zuerst scripts/stop_https.ps1 ausfuehren.'
    }
}

$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/health' -TimeoutSec 5
if ($health.service -ne 'trainmaps-development' -or $health.status -ne 'ok') {
    throw 'Die lokale trainmaps-API antwortet nicht wie erwartet.'
}

$mode = if ($HealthOnly) { 'health-only' } elseif ($Staging) { 'staging' } else { 'production' }
$env:TRAINMAPS_CADDY_DATA = (Join-Path $projectRoot ".local\caddy-$mode").Replace('\', '/')
$env:TRAINMAPS_ACME_DIRECTORY = if ($Staging) {
    'https://acme-staging-v02.api.letsencrypt.org/directory'
} else {
    'https://acme-v02.api.letsencrypt.org/directory'
}
$configName = if ($HealthOnly) { 'deploy\Caddyfile.health' } else { 'deploy\Caddyfile' }
$config = Join-Path $projectRoot $configName
& $caddy validate --config $config --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddy-Konfiguration ist ungueltig.' }

$process = Start-Process -FilePath $caddy -ArgumentList @('run', '--config', ('"' + $config + '"'), '--adapter', 'caddyfile') `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $projectRoot '.local\https.stdout.log') `
    -RedirectStandardError (Join-Path $projectRoot '.local\https.stderr.log')
@{
    pid = $process.Id
    started_at = $process.StartTime.ToUniversalTime().ToString('o')
    mode = $mode
    binary = $caddy
} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
Write-Output "Caddy gestartet (PID $($process.Id), $mode). Zertifikatsstatus: .local/https.stderr.log"
Write-Output 'Der Start allein bestaetigt noch keine erfolgreiche Ausstellung oder externe Erreichbarkeit.'
