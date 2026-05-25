param(
    [switch]$SkipReleaseBuild
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$root = Split-Path -Parent $scriptDir
Set-Location $root

if (-not $SkipReleaseBuild) {
    Write-Host "[1/2] Building release payload..." -ForegroundColor Cyan
    & (Join-Path $scriptDir "build.ps1")
}
else {
    Write-Host "[1/2] Skipping release build as requested." -ForegroundColor Yellow
}

$issPath = Join-Path $root "installer\BasketballBroadcastControl.iss"

$isccCandidates = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $isccCandidates -or $isccCandidates.Count -eq 0) {
    throw "Inno Setup Compiler (ISCC.exe) not found. Install Inno Setup 6 and retry."
}

$iscc = $isccCandidates[0]

Write-Host "[2/2] Building setup.exe with Inno Setup..." -ForegroundColor Cyan
& $iscc $issPath

$outputDir = Join-Path $root "release\installer"
Write-Host "Done. Installer output folder: $outputDir" -ForegroundColor Green
