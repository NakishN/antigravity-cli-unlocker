# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v2.1                       ║
# ║          Regional Access & DNS Routing for Windows                   ║
# ╚══════════════════════════════════════════════════════════════════════╝

[CmdletBinding()]
param (
    [switch]$Restore
)

$IssuesUrl = "https://github.com/NakishN/antigravity-cli-unlocker/issues"

$Host.UI.RawUI.ForegroundColor = 'Cyan'
Write-Host "===================================================================="
Write-Host "                  Antigravity CLI Unlocker v2.1                     "
Write-Host "          Regional Access & DNS Routing for Windows                 "
Write-Host "===================================================================="
$Host.UI.RawUI.ForegroundColor = 'Gray'
Write-Host ""

$BackupDir = Join-Path $env:LOCALAPPDATA "antigravity-unlocker"
$BackupFile = Join-Path $BackupDir "agy.exe.original.bak"
$DnsPrimary = "111.88.96.50"
$DnsSecondary = "111.88.96.51"

function Show-IssuesHelp {
    Write-Host "`n Support & Troubleshooting:" -ForegroundColor Yellow
    Write-Host "   $IssuesUrl`n" -ForegroundColor Cyan
}

function Find-AgyBinary {
    $Candidates = @(
        "$env:USERPROFILE\.antigravity\bin\agy.exe",
        "$env:LOCALAPPDATA\Programs\Antigravity\bin\agy.exe",
        "$env:ProgramFiles\Antigravity\bin\agy.exe",
        (Get-Command agy.exe -ErrorAction SilentlyContinue).Path
    )
    foreach ($path in $Candidates) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }
    return $null
}

if ($Restore) {
    Write-Host "[!] Restoring system state..." -ForegroundColor Yellow
    $AgyBin = Find-AgyBinary
    if (Test-Path $BackupFile) {
        if (-not $AgyBin) { $AgyBin = "$env:USERPROFILE\.antigravity\bin\agy.exe" }
        Copy-Item -Path $BackupFile -Destination $AgyBin -Force
        Write-Host "[OK] Binary agy.exe restored from backup." -ForegroundColor Green
    } else {
        Write-Host "[WARN] Backup file not found." -ForegroundColor Yellow
    }

    try {
        $Adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        if ($Adapter) {
            Set-DnsClientServerAddress -InterfaceIndex $Adapter.ifIndex -ResetServerAddresses
            Write-Host "[OK] DNS server configuration reset to default (DHCP)." -ForegroundColor Green
        }
    } catch {
        Write-Host "[WARN] Run script as Administrator to reset DNS settings." -ForegroundColor Yellow
    }

    ipconfig /flushdns | Out-Null
    Write-Host "[OK] System restore completed successfully." -ForegroundColor Green
    exit 0
}

Write-Host "[1/3] Binary Verification and Backup..." -ForegroundColor Magenta
$AgyPath = Find-AgyBinary

if (-not $AgyPath) {
    Write-Host "[ERROR] Target binary 'agy.exe' not found on system." -ForegroundColor Red
    Write-Host "  Install Antigravity CLI or add directory to PATH." -ForegroundColor Yellow
    Show-IssuesHelp
    exit 1
}

Write-Host "  [OK] Located agy.exe: $AgyPath" -ForegroundColor Green

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

if (-not (Test-Path $BackupFile)) {
    Copy-Item -Path $AgyPath -Destination $BackupFile -Force
    Write-Host "  [OK] Backup created: $BackupFile" -ForegroundColor Green
} else {
    Write-Host "  [OK] Backup verified: $BackupFile" -ForegroundColor Green
}

Write-Host "`n[2/3] Machine Code Gate Patching..." -ForegroundColor Magenta

$PyCode = @"
import sys, os, re

agy_path = r'$AgyPath'
try:
    with open(agy_path, 'rb') as f:
        data = bytearray(f.read())
except Exception as e:
    print(f"ERROR:{e}")
    sys.exit(1)

sig = re.compile(rb'\x48\x85\xc0\x0f\x84....\x80\x78\x08\x00\x0f\x85....', re.S)
patched = re.compile(rb'\x48\x85\xc0\x0f\x84....\x48\x85\xc0\x90\x0f\x85....', re.S)
fix = b'\x48\x85\xc0\x90'

if list(patched.finditer(data)):
    print("ALREADY")
    sys.exit(0)

hits = [m.start() + 9 for m in sig.finditer(data)]
if not hits:
    print("MISSING")
    sys.exit(0)

for off in hits:
    data[off:off + len(fix)] = fix

tmp_path = agy_path + '.tmp'
try:
    with open(tmp_path, 'wb') as f:
        f.write(data)
    os.replace(tmp_path, agy_path)
    print("OK:" + str(len(hits)))
except Exception as e:
    if os.path.exists(tmp_path): os.unlink(tmp_path)
    print(f"ERROR:{e}")
    sys.exit(1)
"@

$PyRes = python -c "$PyCode" 2>$null

if ($PyRes -like "OK:*") {
    Write-Host "  [OK] Patch applied successfully." -ForegroundColor Green
} elseif ($PyRes -eq "ALREADY") {
    Write-Host "  [OK] Binary is already patched." -ForegroundColor Green
} elseif ($PyRes -eq "MISSING") {
    Write-Host "  [WARN] Gate signatures not matched." -ForegroundColor Yellow
} else {
    Write-Host "  [INFO] Fallback patching via PowerShell..." -ForegroundColor Yellow
    try {
        $Bytes = [System.IO.File]::ReadAllBytes($AgyPath)
        $Patched = $false
        for ($i = 0; $i -lt ($Bytes.Length - 15); $i++) {
            if ($Bytes[$i] -eq 0x80 -and $Bytes[$i+1] -eq 0x78 -and $Bytes[$i+2] -eq 0x08 -and $Bytes[$i+3] -eq 0x00 -and $Bytes[$i+4] -eq 0x0F -and $Bytes[$i+5] -eq 0x85) {
                $Bytes[$i] = 0x90
                $Bytes[$i+1] = 0x90
                $Bytes[$i+2] = 0x90
                $Bytes[$i+3] = 0x90
                $Patched = $true
            }
        }
        if ($Patched) {
            [System.IO.File]::WriteAllBytes($AgyPath, $Bytes)
            Write-Host "  [OK] Patch applied via PowerShell." -ForegroundColor Green
        } else {
            Write-Host "  [OK] Binary already patched." -ForegroundColor Green
        }
    } catch {
        Write-Host "  [ERROR] Writing binary failed. Close agy and retry." -ForegroundColor Red
        Show-IssuesHelp
    }
}

Write-Host "`n[3/3] System DNS Routing Configuration..." -ForegroundColor Magenta

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "  [WARN] Administrator privileges required for DNS setup." -ForegroundColor Yellow
    Write-Host "  [INFO] Re-run PowerShell script as Administrator." -ForegroundColor Yellow
} else {
    try {
        $Adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        if ($Adapter) {
            Set-DnsClientServerAddress -InterfaceIndex $Adapter.ifIndex -ServerAddresses ($DnsPrimary, $DnsSecondary)
            Write-Host "  [OK] Smart DNS ($DnsPrimary, $DnsSecondary) applied to interface: $($Adapter.Name)" -ForegroundColor Green
            ipconfig /flushdns | Out-Null
            Write-Host "  [OK] DNS cache flushed." -ForegroundColor Green
        } else {
            Write-Host "  [WARN] Active network interface not found." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [ERROR] DNS configuration failed: $_" -ForegroundColor Red
        Show-IssuesHelp
    }
}

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "             Antigravity CLI Unlock Completed                       " -ForegroundColor Green
Write-Host "====================================================================`n" -ForegroundColor Green
Write-Host "  Execute: agy" -ForegroundColor White
Write-Host "  Restore: .\antigravity_unlock_windows.ps1 -Restore" -ForegroundColor Gray
Write-Host "  Support: $IssuesUrl" -ForegroundColor Cyan
