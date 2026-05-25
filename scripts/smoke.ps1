param(
    [string]$ReleaseDir = "release\BasketballStats",
    [int]$Port = 8081
)

$ErrorActionPreference = "Stop"
$release = Resolve-Path $ReleaseDir
$required = @("manager.exe", "main.exe", "overlay.html", "player.html", "player-full.html", "json\config.json", "json\result.json", "json\player.json")
foreach ($item in $required) {
    $path = Join-Path $release $item
    if (-not (Test-Path $path)) { throw "Missing release file: $item" }
}

$prefix = "http://localhost:$Port/"
$job = Start-Job -ScriptBlock {
    param($root, $prefix)
    Add-Type -AssemblyName System.Net.HttpListener
    $listener = [System.Net.HttpListener]::new()
    $listener.Prefixes.Add($prefix)
    $listener.Start()
    while ($listener.IsListening) {
        $ctx = $listener.GetContext()
        $local = $ctx.Request.Url.LocalPath.TrimStart("/")
        if (-not $local) { $local = "overlay.html" }
        $file = Join-Path $root $local
        if (Test-Path $file) {
            $bytes = [System.IO.File]::ReadAllBytes($file)
            $ctx.Response.StatusCode = 200
            $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            $ctx.Response.StatusCode = 404
        }
        $ctx.Response.Close()
    }
} -ArgumentList $release, $prefix

try {
    Start-Sleep -Milliseconds 500
    $checks = @("overlay.html", "player.html", "player-full.html", "json/result.json", "json/player.json")
    $results = foreach ($check in $checks) {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri ($prefix + $check) -TimeoutSec 5
        @{ path = $check; status = $resp.StatusCode }
    }
    $report = @{ ok = $true; checked_at = (Get-Date).ToUniversalTime().ToString("o"); results = $results }
    $report | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $release "smoke-report.json")
} finally {
    Stop-Job $job -ErrorAction SilentlyContinue | Out-Null
    Remove-Job $job -Force -ErrorAction SilentlyContinue | Out-Null
}

