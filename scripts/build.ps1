[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if ($Clean) {
    Remove-Item -LiteralPath (Join-Path $projectRoot 'build') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $projectRoot 'dist') -Recurse -Force -ErrorAction SilentlyContinue
}

python -m PyInstaller `
    --noconfirm `
    --windowed `
    --name FlashForge `
    --icon "$projectRoot\src\flashforge\assets\flashforge.ico" `
    --specpath build `
    --paths src `
    --exclude-module pytest `
    --exclude-module _pytest `
    --exclude-module IPython `
    --exclude-module jupyter `
    --exclude-module matplotlib `
    --collect-data flashforge `
    --add-data "$projectRoot\src\flashforge\prompts;flashforge/prompts" `
    src/flashforge/app.py
