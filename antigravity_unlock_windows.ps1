# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v2.1                       ║
# ║        Обход региональных ограничений и DNS для Windows              ║
# ╚══════════════════════════════════════════════════════════════════════╝

[CmdletBinding()]
param (
    [switch]$Restore
)

$IssuesUrl = "https://github.com/NakishN/antigravity-cli-unlocker/issues"

$Host.UI.RawUI.ForegroundColor = 'Cyan'
Write-Host "===================================================================="
Write-Host "                  Antigravity CLI Unlocker v2.1                     "
Write-Host "        Обход региональных ограничений и DNS для Windows            "
Write-Host "===================================================================="
$Host.UI.RawUI.ForegroundColor = 'Gray'
Write-Host ""

$BackupDir = Join-Path $env:LOCALAPPDATA "antigravity-unlocker"
$BackupFile = Join-Path $BackupDir "agy.exe.original.bak"
$DnsPrimary = "111.88.96.50"
$DnsSecondary = "111.88.96.51"

function Show-IssuesHelp {
    Write-Host "`n Поддержка и решение проблем:" -ForegroundColor Yellow
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
    Write-Host "[!] Восстановление исходного состояния..." -ForegroundColor Yellow
    $AgyBin = Find-AgyBinary
    if (Test-Path $BackupFile) {
        if (-not $AgyBin) { $AgyBin = "$env:USERPROFILE\.antigravity\bin\agy.exe" }
        Copy-Item -Path $BackupFile -Destination $AgyBin -Force
        Write-Host "[ОК] Исполняемый файл agy.exe восстановлен из резервной копии." -ForegroundColor Green
    } else {
        Write-Host "[ВНИМАНИЕ] Файл резервной копии не найден." -ForegroundColor Yellow
    }

    try {
        $Adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        if ($Adapter) {
            Set-DnsClientServerAddress -InterfaceIndex $Adapter.ifIndex -ResetServerAddresses
            Write-Host "[ОК] Настройки DNS-серверов сброшены к значениям по умолчанию (DHCP)." -ForegroundColor Green
        }
    } catch {
        Write-Host "[ВНИМАНИЕ] Для сброса DNS перезапустите скрипт от имени администратора." -ForegroundColor Yellow
    }

    ipconfig /flushdns | Out-Null
    Write-Host "[ОК] Восстановление системы завершено." -ForegroundColor Green
    exit 0
}

Write-Host "[1/3] Проверка бинарного файла и бэкап..." -ForegroundColor Magenta
$AgyPath = Find-AgyBinary

if (-not $AgyPath) {
    Write-Host "[ОШИБКА] Целевой файл 'agy.exe' не найден в системе." -ForegroundColor Red
    Write-Host "  Установите Antigravity CLI или добавьте путь к нему в переменные среды PATH." -ForegroundColor Yellow
    Show-IssuesHelp
    exit 1
}

Write-Host "  [ОК] Найден файл agy.exe: $AgyPath" -ForegroundColor Green

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

if (-not (Test-Path $BackupFile)) {
    Copy-Item -Path $AgyPath -Destination $BackupFile -Force
    Write-Host "  [ОК] Резервная копия создана: $BackupFile" -ForegroundColor Green
} else {
    Write-Host "  [ОК] Резервная копия подтверждена: $BackupFile" -ForegroundColor Green
}

Write-Host "`n[2/3] Патч регионального затвора в машинном коде..." -ForegroundColor Magenta

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
    Write-Host "  [ОК] Патч успешно применен." -ForegroundColor Green
} elseif ($PyRes -eq "ALREADY") {
    Write-Host "  [ОК] Файл уже пропатчен ранее." -ForegroundColor Green
} elseif ($PyRes -eq "MISSING") {
    Write-Host "  [ВНИМАНИЕ] Сигнатуры регионального затвора не совпали." -ForegroundColor Yellow
} else {
    Write-Host "  [ИНФО] Применение патча через резервный механизм PowerShell..." -ForegroundColor Yellow
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
            Write-Host "  [ОК] Патч применен через PowerShell." -ForegroundColor Green
        } else {
            Write-Host "  [ОК] Файл уже содержит патч." -ForegroundColor Green
        }
    } catch {
        Write-Host "  [ОШИБКА] Ошибка записи файла. Завершите процесс agy и повторите попытку." -ForegroundColor Red
        Show-IssuesHelp
    }
}

Write-Host "`n[3/3] Настройка системной DNS-маршрутизации..." -ForegroundColor Magenta

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "  [ВНИМАНИЕ] Для настройки DNS необходимы права администратора." -ForegroundColor Yellow
    Write-Host "  [ИНФО] Перезапустите PowerShell от имени администратора." -ForegroundColor Yellow
} else {
    try {
        $Adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        if ($Adapter) {
            Set-DnsClientServerAddress -InterfaceIndex $Adapter.ifIndex -ServerAddresses ($DnsPrimary, $DnsSecondary)
            Write-Host "  [ОК] Серверы DNS ($DnsPrimary, $DnsSecondary) применены к интерфейсу: $($Adapter.Name)" -ForegroundColor Green
            ipconfig /flushdns | Out-Null
            Write-Host "  [ОК] Кэш DNS успешно очищен." -ForegroundColor Green
        } else {
            Write-Host "  [ВНИМАНИЕ] Активный сетевой адаптер не обнаружен." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [ОШИБКА] Ошибка при установке DNS-серверов: $_" -ForegroundColor Red
        Show-IssuesHelp
    }
}

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "             Разблокировка Antigravity CLI завершена                " -ForegroundColor Green
Write-Host "====================================================================`n" -ForegroundColor Green
Write-Host "  Запуск:    agy" -ForegroundColor White
Write-Host "  Откат:     .\antigravity_unlock_windows.ps1 -Restore" -ForegroundColor Gray
Write-Host "  Поддержка: $IssuesUrl" -ForegroundColor Cyan
