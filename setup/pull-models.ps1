<#
LOOM remake - local model setup (Windows PowerShell 5.1+).

  powershell -ExecutionPolicy Bypass -File remake\setup\pull-models.ps1                 # Ollama models only
  powershell -ExecutionPolicy Bypass -File remake\setup\pull-models.ps1 -OpenWeights    # + speech/vision weights
  powershell -ExecutionPolicy Bypass -File remake\setup\pull-models.ps1 -VerifyOnly     # check, download nothing

Pulls are retried with back-off (Ollama resumes partial blobs), then each model is smoke-tested.
The model list mirrors spec/03-local-ai.md section 2. Keep the two in sync.
#>
param(
    [switch]$OpenWeights,
    [switch]$VerifyOnly,
    [switch]$ConfigureServer,   # persist the Ollama server settings of spec/03-local-ai.md section 3 (user env)
    [switch]$Fallbacks,         # also pull the fallback models compared in the Stage 0 spike
    [int]$MaxTries = 15
)

$ErrorActionPreference = 'Continue'

if ($ConfigureServer) {
    $settings = [ordered]@{
        OLLAMA_HOST               = '127.0.0.1:11434'
        OLLAMA_MAX_LOADED_MODELS  = '1'
        OLLAMA_NUM_PARALLEL       = '1'
        OLLAMA_FLASH_ATTENTION    = '1'
        OLLAMA_KV_CACHE_TYPE      = 'q8_0'
        OLLAMA_CONTEXT_LENGTH     = '8192'
        OLLAMA_KEEP_ALIVE         = '10m'
    }
    foreach ($k in $settings.Keys) {
        [Environment]::SetEnvironmentVariable($k, $settings[$k], 'User')
        Write-Host "set $k=$($settings[$k]) (user)"
    }
    Write-Host 'Quit Ollama from the tray and start it again so the server picks these up.'
}

# role -> model tag (spec/03-local-ai.md, table 2.1)
$OllamaModels = [ordered]@{
    'embed'  = 'qwen3-embedding:0.6b'
    'ocr'    = 'glm-ocr:q8_0'
    'brain'  = 'qwen3.5:9b'
    'safety' = 'granite4.1-guardian:8b-q4_K_M'
    'judge'  = 'gemma4:e4b'
}
if ($Fallbacks) {
    $OllamaModels['brain_small'] = 'qwen3.5:4b'
    $OllamaModels['judge_alt']   = 'gemma4:e4b-it-qat'
}

# Open-weight models used outside Ollama (spec/03-local-ai.md, table 2.2) are listed in setup/fetch_weights.py and
# downloaded into the HF cache through the project's uv environment (not the system Python).

function Test-OllamaUp {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 5 | Out-Null; return $true }
    catch { return $false }
}

function Test-ModelPresent([string]$tag) {
    $list = (& ollama list) -join "`n"
    return $list -match [regex]::Escape($tag)
}

function Invoke-Pull([string]$tag) {
    for ($i = 1; $i -le $MaxTries; $i++) {
        Write-Host ("  pull {0} (try {1}/{2})" -f $tag, $i, $MaxTries)
        # via cmd so PowerShell 5.1 does not turn Ollama's progress output (stderr) into NativeCommandError noise
        & cmd /c "ollama pull $tag >NUL 2>&1"
        if ($LASTEXITCODE -eq 0 -and (Test-ModelPresent $tag)) { return $true }
        $wait = [Math]::Min(120, 10 * $i)
        Write-Host "  network hiccup - retrying in $wait s"
        Start-Sleep -Seconds $wait
    }
    return $false
}

function Test-Model([string]$role, [string]$tag) {
    if ($role -eq 'embed') {
        $body = @{ model = $tag; input = 'loom smoke test' } | ConvertTo-Json
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/embed' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 300
        $ok = $r.embeddings.Count -eq 1
        $info = "dim=$($r.embeddings[0].Count)"
    } else {
        $body = @{ model = $tag; prompt = 'Reply with the single word: ready'; stream = $false; think = $false;
                   options = @{ num_ctx = 2048; num_predict = 16 }; keep_alive = 0 } | ConvertTo-Json -Depth 4
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 600
        $ok = [bool]$r.response -or [bool]$r.thinking
        # guardian models answer in their own format (e.g. "<score> no </score>"): any reply counts as alive
        $text = ("$($r.response)".Trim() -replace '\s+', ' ')
        if ($text.Length -gt 40) { $text = $text.Substring(0, 40) }
        $info = '"' + $text + '"'
    }
    return @{ ok = $ok; info = $info }
}

# ---------------------------------------------------------------- Ollama
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Write-Error 'ollama not on PATH - install from ollama.com first'; exit 1 }
if (-not (Test-OllamaUp)) {
    Write-Host 'Starting ollama serve ...'
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
    Start-Sleep -Seconds 5
    if (-not (Test-OllamaUp)) { Write-Error 'Ollama server not reachable on 127.0.0.1:11434'; exit 1 }
}

$drive = Get-PSDrive -Name ($env:USERPROFILE.Substring(0, 1))
Write-Host ("Free disk on {0}: {1:N1} GB (Ollama models need ~22 GB, open weights ~4 GB)" -f $drive.Name, ($drive.Free / 1GB))

$results = @()
foreach ($role in $OllamaModels.Keys) {
    $tag = $OllamaModels[$role]
    Write-Host "[$role] $tag"
    $present = Test-ModelPresent $tag
    if (-not $present -and -not $VerifyOnly) { $present = Invoke-Pull $tag }
    if (-not $present) { $results += [pscustomobject]@{ role = $role; model = $tag; status = 'MISSING'; info = '' }; continue }
    try   { $t = Test-Model $role $tag; $status = if ($t.ok) { 'OK' } else { 'NO-OUTPUT' }; $info = $t.info }
    catch { $status = 'ERROR'; $info = $_.Exception.Message }
    $results += [pscustomobject]@{ role = $role; model = $tag; status = $status; info = $info }
}

# ---------------------------------------------------------------- open weights (optional)
if ($OpenWeights) {
    Write-Host 'Pre-downloading open-weight models into the Hugging Face cache ...'
    $fetch = Join-Path $PSScriptRoot 'fetch_weights.py'
    $uvArgs = @('run', '--project', (Split-Path $PSScriptRoot -Parent), '--group', 'setup', 'python', $fetch)
    if ($VerifyOnly) { $uvArgs += '--verify' }
    & uv @uvArgs
}

Write-Host ''
$results | Format-Table -AutoSize
if ($results.status -contains 'MISSING' -or $results.status -contains 'ERROR') { exit 2 }
Write-Host 'All Ollama models present and answering.'
