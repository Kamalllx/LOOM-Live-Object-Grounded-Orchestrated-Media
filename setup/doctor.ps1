<#
LOOM remake - machine check (FR-OPS-02). Thin wrapper around `loom doctor`.

  powershell -ExecutionPolicy Bypass -File remake\setup\doctor.ps1            # full check incl. model smoke calls
  powershell -ExecutionPolicy Bypass -File remake\setup\doctor.ps1 -NoSmoke   # skip loading every model
#>
param([switch]$NoSmoke, [switch]$Json)

$root = Split-Path $PSScriptRoot -Parent
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error 'uv is not on PATH - winget install --id astral-sh.uv -e, then open a new terminal'
    exit 1
}
$uvArgs = @('run', '--project', $root, 'loom', 'doctor')
if ($NoSmoke) { $uvArgs += '--no-smoke' }
if ($Json) { $uvArgs += '--json' }
& uv @uvArgs
exit $LASTEXITCODE
