<#
.SYNOPSIS
    Poll NVIDIA GPU VRAM usage every N seconds for one specific GPU (by name).

.DESCRIPTION
    Watches the RTX 4070 Ti SUPER (matched by name substring, default "4070 Ti SUPER")
    while the NInfer engine loads and serves. Prints one line per sample:
    timestamp, GPU name, used / total MiB, free MiB and GPU utilization.
    Press Ctrl+C to stop.

.PARAMETER IntervalSeconds
    Polling interval in seconds (default 2).

.PARAMETER GpuName
    Case-insensitive name substring used to pick the GPU (default "4070 Ti SUPER").
    Use -GpuName "5070 Ti" etc. for other cards.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\watch_vram.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\watch_vram.ps1 -IntervalSeconds 2 -GpuName "4070 Ti SUPER"
#>

param(
    [int]$IntervalSeconds = 2,
    [string]$GpuName = "4070 Ti SUPER"
)

$ErrorActionPreference = "Stop"

function Resolve-NvidiaSmi {
    $found = Get-Command -Name nvidia-smi -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $candidates = @(
        (Join-Path $env:SystemRoot "System32\nvidia-smi.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    throw ("nvidia-smi.exe not found in PATH or standard locations. " +
           "Install/repair the NVIDIA driver, or add its directory to PATH.")
}

function Get-GpuLines {
    param([string]$SmiPath)
    # nounits => MiB integers; noheader => one line per GPU
    $out = & $SmiPath --query-gpu=name,memory.used,memory.total,utilization.gpu `
                      --format=csv,noheader,nounits 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ("nvidia-smi exited with code {0}: {1}" -f $LASTEXITCODE, ($out -join " "))
    }
    return @($out)
}

try {
    $smi = Resolve-NvidiaSmi
} catch {
    Write-Host ("[ERROR] {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}

Write-Host ("watch_vram: polling GPU matching '{0}' every {1}s via '{2}'." -f $GpuName, $IntervalSeconds, $smi)
Write-Host "Press Ctrl+C to stop."
Write-Host ("{0}  {1}" -f "timestamp".PadRight(19), "gpu / vram")

try {
    while ($true) {
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        try {
            $lines = Get-GpuLines -SmiPath $smi
            $target = $lines | Where-Object { $_ -like ("*{0}*" -f $GpuName) } | Select-Object -First 1
            if ($null -eq $target) {
                Write-Host ("{0}  GPU matching '{1}' not found. Detected: {2}" -f
                            $ts, $GpuName, ($lines -join " | "))
            } else {
                # Name may itself contain no comma here; split on CSV comma.
                $parts = ($target -split ",") | ForEach-Object { $_.Trim() }
                $gName  = $parts[0]
                $used   = 0L
                $total  = 0L
                if (-not [int64]::TryParse($parts[1], [ref]$used)) {
                    throw ("cannot parse used MiB from '{0}'" -f $target)
                }
                if (-not [int64]::TryParse($parts[2], [ref]$total)) {
                    throw ("cannot parse total MiB from '{0}'" -f $target)
                }
                $util  = $parts[3]
                $free  = $total - $used
                Write-Host ("{0}  {1}  used {2} MiB / {3} MiB  free {4} MiB  util {5}%" -f
                            $ts, $gName, $used, $total, $free, $util)
            }
        } catch {
            Write-Host ("{0}  query failed: {1}" -f $ts, $_.Exception.Message)
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
} finally {
    Write-Host "watch_vram stopped."
}
