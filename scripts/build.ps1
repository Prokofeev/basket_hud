param(
    [string]$ReleaseDir = "release\BasketballStats"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Remove-Item -Recurse -Force build, dist, release -ErrorAction SilentlyContinue
python -m pip install -r requirements-dev.txt
pyinstaller --clean main.spec
pyinstaller --clean manager.spec

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $ReleaseDir "json\players") | Out-Null

Copy-Item dist\main.exe (Join-Path $ReleaseDir "main.exe")
Copy-Item dist\manager.exe (Join-Path $ReleaseDir "manager.exe")
Copy-Item overlay.html, player.html, player-full.html, server.ps1, start_server.bat $ReleaseDir
if (Test-Path js) { Copy-Item -Recurse js (Join-Path $ReleaseDir "js") }
Copy-Item json\config.json, json\result.json, json\player.json (Join-Path $ReleaseDir "json")
Copy-Item json\logo-home.png, json\logo-away.png (Join-Path $ReleaseDir "json") -ErrorAction SilentlyContinue

$manifest = @{
    version = "0.1.0"
    built_at = (Get-Date).ToUniversalTime().ToString("o")
    python = (python --version)
    files = Get-ChildItem -Recurse $ReleaseDir | Where-Object { -not $_.PSIsContainer } | ForEach-Object {
        @{
            path = $_.FullName.Substring((Resolve-Path $ReleaseDir).Path.Length + 1)
            sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
            size = $_.Length
        }
    }
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $ReleaseDir "manifest.json")

