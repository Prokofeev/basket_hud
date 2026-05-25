param(
    [int]$Port = 8081,
    [ValidateSet('local', 'lan')]
    [string]$Mode = 'local'
)

# Basketball Stats HTTP Server

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$rootFull = [System.IO.Path]::GetFullPath($root)
$hostPrefix = if ($Mode -eq 'lan') { '+' } else { 'localhost' }
$publicHost = if ($Mode -eq 'lan') { $env:COMPUTERNAME } else { 'localhost' }

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://$hostPrefix`:$Port/")

try {
    $listener.Start()
} catch {
    Write-Host "ОШИБКА: порт $Port занят или недоступен. Закройте другие программы и повторите." -ForegroundColor Red
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

Write-Host ""
Write-Host "  Basketball Stats Server запущен!" -ForegroundColor Green
Write-Host "  URL для OBS/vMix: http://$publicHost`:$Port/overlay.html" -ForegroundColor Cyan
Write-Host "  Нажмите Ctrl+C для остановки." -ForegroundColor Yellow
Write-Host ""

$mime = @{
    '.html' = 'text/html; charset=utf-8'
    '.json' = 'application/json; charset=utf-8'
    '.js'   = 'application/javascript; charset=utf-8'
    '.css'  = 'text/css; charset=utf-8'
    '.png'  = 'image/png'
    '.jpg'  = 'image/jpeg'
}

try {
    while ($listener.IsListening) {
        $ctx  = $listener.GetContext()
        $lp   = $ctx.Request.Url.LocalPath.TrimStart('/')
        if ($lp -eq '') { $lp = 'overlay.html' }
        $fp   = [System.IO.Path]::GetFullPath((Join-Path $root $lp))
        $res  = $ctx.Response
        $res.Headers.Add('Access-Control-Allow-Origin', '*')
        $res.Headers.Add('Cache-Control', 'no-cache, no-store')

        if (-not $fp.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            $body = [System.Text.Encoding]::UTF8.GetBytes('403 Forbidden')
            $res.StatusCode      = 403
            $res.ContentType     = 'text/plain'
            $res.ContentLength64 = $body.Length
            $res.OutputStream.Write($body, 0, $body.Length)
        } elseif (Test-Path $fp -PathType Leaf) {
            $bytes = [System.IO.File]::ReadAllBytes($fp)
            $ext   = [System.IO.Path]::GetExtension($fp).ToLower()
            $res.ContentType     = if ($mime[$ext]) { $mime[$ext] } else { 'application/octet-stream' }
            $res.ContentLength64 = $bytes.Length
            $res.StatusCode      = 200
            $res.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            $body = [System.Text.Encoding]::UTF8.GetBytes('404 Not Found')
            $res.StatusCode      = 404
            $res.ContentType     = 'text/plain'
            $res.ContentLength64 = $body.Length
            $res.OutputStream.Write($body, 0, $body.Length)
        }
        $res.Close()
    }
} finally {
    $listener.Stop()
    $listener.Close()
}
