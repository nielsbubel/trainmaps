#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$caddy = Join-Path $projectRoot '.local\tools\caddy-2.11.4\caddy.exe'
if (-not (Test-Path -LiteralPath $caddy)) { throw 'Caddy wurde noch nicht installiert.' }
$ruleName = 'trainmaps-caddy-http-https'
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    throw 'Die trainmaps-Regel existiert bereits. Bestehende Regel zuerst pruefen.'
}
New-NetFirewallRule -Name $ruleName -DisplayName 'trainmaps Caddy HTTP/HTTPS' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 80,443 `
    -Program $caddy -Profile Any | Select-Object Name,Enabled,Direction,Action
