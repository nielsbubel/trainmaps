[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $projectRoot '.local\https-process.json'
if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Output 'Kein gespeicherter trainmaps-HTTPS-Prozess.'
    return
}
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$expectedBinary = Join-Path $projectRoot '.local\tools\caddy-2.11.4\caddy.exe'
$process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if ($process) {
    if ($process.Path -ne $expectedBinary -or
        $process.StartTime.ToUniversalTime() -ne ([datetime]$state.started_at).ToUniversalTime()) {
        throw 'Prozessidentitaet stimmt nicht mehr ueberein; es wurde nichts beendet.'
    }
    Stop-Process -Id $process.Id
}
Remove-Item -LiteralPath $stateFile
Write-Output 'trainmaps-HTTPS-Prozess beendet. Zertifikate und API-Daten bleiben erhalten.'
