$ErrorActionPreference = "SilentlyContinue"

$ports = @(5173, 8003, 8001)

foreach ($port in $ports) {
    $pids = @()
    try {
        $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    } catch {
        $pids = @()
    }

    foreach ($pidValue in ($pids | Where-Object { $_ -gt 0 })) {
        try {
            Stop-Process -Id $pidValue -Force -ErrorAction Stop
            Write-Host "[dev] released port $port from PID $pidValue"
        } catch {
            Write-Host "[dev] skip port $port PID ${pidValue}: $($_.Exception.Message)"
        }
    }
}

Write-Host "[dev] using backend http://127.0.0.1:8003 and frontend http://127.0.0.1:5173/frontend/"
