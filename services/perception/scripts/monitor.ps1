# Logs GPU temperature/power/memory and CPU load every 2 s, so a crash leaves evidence.
param([string]$Out = "out/monitor.csv", [int]$Seconds = 1800)
New-Item -ItemType Directory -Force (Split-Path $Out) | Out-Null
"time,gpu_temp_c,gpu_power_w,gpu_mem_mib,gpu_util,cpu_pct" | Out-File $Out -Encoding utf8
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
  $g = (nvidia-smi --query-gpu=temperature.gpu,power.draw,memory.used,utilization.gpu --format=csv,noheader,nounits) -replace '\s', ''
  $c = [math]::Round((Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average)
  "$(Get-Date -Format HH:mm:ss),$g,$c" | Out-File $Out -Append -Encoding utf8
  Start-Sleep 2
}
