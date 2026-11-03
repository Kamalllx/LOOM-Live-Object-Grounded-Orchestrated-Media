<#
S0 exit criterion "Stopping Ollama makes /api/ready report the missing roles within 30 s" - live check.

Starts `loom gateway`, confirms /api/ready is green, stops the Ollama tray app + server, measures how long until
/api/ready returns 503 with the roles listed, then restarts Ollama (with the user-level OLLAMA_* settings) and waits
for green again. Writes data/eval/outage_ready.json.

  powershell -ExecutionPolicy Bypass -File remake\setup\outage_ready.ps1
#>
param([int]$Port = 8000, [int]$LimitS = 30)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$ready = "http://127.0.0.1:$Port/api/ready"

function Get-Ready {
    # curl.exe keeps the 503 body (Invoke-WebRequest on PowerShell 5.1 drops it on error status codes)
    $tmp = [IO.Path]::GetTempFileName()
    try {
        $code = & curl.exe -s -o $tmp -w '%{http_code}' --max-time 10 $ready
        $body = $null
        if ((Get-Item $tmp).Length -gt 0) { $body = Get-Content $tmp -Raw | ConvertFrom-Json }
        return @{ code = [int]$code; body = $body }
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

function Start-OllamaApp {
    foreach ($k in 'OLLAMA_HOST','OLLAMA_MAX_LOADED_MODELS','OLLAMA_NUM_PARALLEL','OLLAMA_FLASH_ATTENTION',
                   'OLLAMA_KV_CACHE_TYPE','OLLAMA_CONTEXT_LENGTH','OLLAMA_KEEP_ALIVE') {
        Set-Item -Path "env:$k" -Value ([Environment]::GetEnvironmentVariable($k, 'User'))
    }
    Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
}

$gw = Start-Process -FilePath 'uv' -ArgumentList @('run', '--project', $root, 'loom', 'gateway', '--port', $Port) `
    -PassThru -WindowStyle Hidden -RedirectStandardError "$root\data\run\gateway_outage.log"
try {
    $deadline = (Get-Date).AddSeconds(90)
    do { Start-Sleep -Milliseconds 500; $s = Get-Ready } until ($s.code -eq 200 -or (Get-Date) -gt $deadline)
    if ($s.code -ne 200) { throw "gateway never became ready (last code $($s.code)): $($s.body | ConvertTo-Json -Depth 5)" }
    Write-Host 'gateway ready; stopping Ollama ...'

    Get-Process | Where-Object { $_.ProcessName -like 'ollama*' } | Stop-Process -Force -Confirm:$false
    $t0 = Get-Date
    do { Start-Sleep -Milliseconds 250; $s = Get-Ready } until ($s.code -eq 503 -or ((Get-Date) - $t0).TotalSeconds -gt 60)
    $flip = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    $missing = $s.body.missing
    Write-Host "ready:false after $flip s; missing: $($missing -join '; ')"

    Write-Host 'restarting Ollama ...'
    Start-OllamaApp
    $t1 = Get-Date
    do { Start-Sleep -Milliseconds 500; $r = Get-Ready } until ($r.code -eq 200 -or ((Get-Date) - $t1).TotalSeconds -gt 90)
    $back = [math]::Round(((Get-Date) - $t1).TotalSeconds, 1)
    Write-Host "ready:true again after $back s"

    $result = [ordered]@{
        criterion = "/api/ready reports missing roles within $LimitS s of Ollama stopping"
        flip_seconds = $flip; pass = ($s.code -eq 503 -and $flip -le $LimitS)
        status_code = $s.code; missing = $missing; recovered_seconds = $back; recovered = ($r.code -eq 200)
        measured_at = (Get-Date).ToUniversalTime().ToString('o')
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 "$root\data\eval\outage_ready.json"
    $result | ConvertTo-Json -Depth 5
} finally {
    if (-not (Get-Process | Where-Object { $_.ProcessName -eq 'ollama' })) { Start-OllamaApp }
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*loom*gateway*--port $Port*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (-not $gw.HasExited) { Stop-Process -Id $gw.Id -Force -ErrorAction SilentlyContinue }
}
