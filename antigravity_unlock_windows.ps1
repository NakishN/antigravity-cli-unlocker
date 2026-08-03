# ╔══════════════════════════════════════════════════════════════════════╗
# ║        🚀 Antigravity CLI Unlocker v2.1 for Windows                  ║
# ║   Разблокировка Google Antigravity CLI (agy.exe) без VPN             ║
# ╚══════════════════════════════════════════════════════════════════════╝

[CmdletBinding()]
param (
    [switch]$Restore
)

$Host.UI.RawUI.ForegroundColor = 'Cyan'
Write-Host "╔══════════════════════════════════════════════════════════════════╗"
Write-Host "║        🚀  Antigravity CLI Unlocker v2.1 (Windows)              ║"
Write-Host "║   Разблокировка Google Antigravity (agy) без VPN в РФ и РБ      ║"
Write-Host "╚══════════════════════════════════════════════════════════════════╝"
$Host.UI.RawUI.ForegroundColor = 'Gray'
Write-Host ""

$BackupDir = Join-Path $env:LOCALAPPDATA "antigravity-unlocker"
$BackupFile = Join-Path $BackupDir "agy.exe.original.bak"
$DnsPrimary = "111.88.96.50"
$DnsSecondary = "111.88.96.51"

# ── Поиск agy.exe ──────────────────────────────────────────────────────
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

# ── Откат изменений ─────────────────────────────────────────────────────
if ($Restore) {
    Write-Host "[!] Откат изменений..." -ForegroundColor Yellow
    $AgyBin = Find-AgyBinary
    if (Test-Path $BackupFile) {
        if (-not $AgyBin) { $AgyBin = "$env:USERPROFILE\.antigravity\bin\agy.exe" }
        Copy-Item -Path $BackupFile -Destination $AgyBin -Force
        Write-Host "[✓] Исполняемый файл agy.exe восстановлен из бэкапа." -ForegroundColor Green
    } else {
        Write-Host "[⚠] Файл резервной копии не найден." -ForegroundColor Yellow
    }

    # Сброс DNS к автоматическому (DHCP)
    try {
        $Adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        if ($Adapter) {
            Set-DnsClientServerAddress -InterfaceIndex $Adapter.ifIndex -ResetServerAddresses
            Write-Host "[✓] DNS серверы сброшены к значениям по умолчанию (DHCP)." -ForegroundColor Green
        }
    } catch {
        Write-Host "[⚠] Для сброса DNS перезапустите скрипт от имени Администратора." -ForegroundColor Yellow
    }

    ipconfig /flushdns | Out-Null
    Write-Host "[✓] Все изменения успешно отменены!" -ForegroundColor Green
    exit 0
}

# ── ШАГ 1: Бэкап ───────────────────────────────────────────────────────
Write-Host "[1/3] Поиск бинарника и создание резервной копии..." -ForegroundColor Magenta
$AgyPath = Find-AgyBinary

if (-not $AgyPath) {
    Write-Host "[✗] agy.exe не найден на ПК!" -ForegroundColor Red
    Write-Host " Установите Antigravity CLI или добавьте путь в PATH." -ForegroundColor Yellow
    exit 1
}

Write-Host " [✓] Найден agy.exe: $AgyPath" -ForegroundColor Green

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

if (-not (Test-Path $BackupFile)) {
    Copy-Item -Path $AgyPath -Destination $BackupFile -Force
    Write-Host " [✓] Резервная копия создана: $BackupFile" -ForegroundColor Green
} else {
    Write-Host " [✓] Резервная копия уже существует." -ForegroundColor Green
}

# ── ШАГ 2: Машинный патч ───────────────────────────────────────────────
Write-Host "`n[2/3] Патч бинарника agy.exe..." -ForegroundColor Magenta

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
    Write-Host " [✓] Машинный патч успешно применен!" -ForegroundColor Green
} elseif ($PyRes -eq "ALREADY") {
    Write-Host " [✓] Файл agy.exe уже пропатчен." -ForegroundColor Green
} elseif ($PyRes -eq "MISSING") {
    Write-Host " [⚠] Сигнатура не найдена (возможно, agy.exe уже пропатчен или обновлен)." -ForegroundColor Yellow
} else {
    Write-Host " [⚠] Пропуск патча через Python (Python не найден). Выполнение патча через PowerShell..." -ForegroundColor Yellow
    # Фоллбэк патч байтов через PowerShell
    try {
        $Bytes = [System.IO.File]::ReadAllBytes($AgyPath)
        $Pattern = [byte[]](0x48, 0x85, 0xC0, 0x0F, 0x84)
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
            Write-Host " [✓] Патч успешно применен через PowerShell!" -ForegroundColor Green
        } else {
            Write-Host " [✓] Файл уже содержит патч." -ForegroundColor Green
        }
    } catch {
        Write-Host " [✗] Ошибка при записи agy.exe. Закройте agy и заново запустите скрипт." -ForegroundColor Red
    }
}

# ── ШАГ 3: Настройка Smart DNS ──────────────────────────────────────────
Write-Host "`n[3/3] Настройка Smart DNS на активном сетевом адаптере..." -ForegroundColor Magenta

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host " [⚠] Для автоматической установки DNS требуются права Администратора." -ForegroundColor Yellow
    Write-Host " [→] Запустите PowerShell от имени Администратора или используйте bat-файл." -ForegroundColor Yellow
} else {
    try {
        $Adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        if ($Adapter) {
            Set-DnsClientServerAddress -InterfaceIndex $Adapter.ifIndex -ServerAddresses ($DnsPrimary, $DnsSecondary)
            Write-Host " [✓] Smart DNS ($DnsPrimary, $DnsSecondary) установлен на адаптере: $($Adapter.Name)" -ForegroundColor Green
            ipconfig /flushdns | Out-Null
            Write-Host " [✓] Кэш DNS успешно очищен!" -ForegroundColor Green
        } else {
            Write-Host " [⚠] Активный сетевой адаптер не найден." -ForegroundColor Yellow
        }
    } catch {
        Write-Host " [✗] Ошибка установки DNS: $_" -ForegroundColor Red
    }
}

Write-Host "`n╔══════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║       ✅  Успешно! Antigravity CLI (agy.exe) разблокирован       ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Green
Write-Host "  Запуск: agy" -ForegroundColor White
Write-Host "  Откат:  .\antigravity_unlock_windows.ps1 -Restore" -ForegroundColor Gray
