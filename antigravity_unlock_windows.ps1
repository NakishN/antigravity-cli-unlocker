# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v2.3.0                     ║
# ║   Обход региональных ограничений, фиксация 1.1.9 & автозапуск (Windows)║
# ╚══════════════════════════════════════════════════════════════════════╝

[CmdletBinding()]
param (
    [switch]$Restore,
    [switch]$DryRun,
    [switch]$Force,
    [switch]$Autostart,
    [switch]$RemoveAutostart,
    [switch]$PinInit,
    [switch]$PinCheck,
    [switch]$Guardian,
    [switch]$Status
)

$IssuesUrl = "https://github.com/NakishN/antigravity-cli-unlocker/issues"
$PythonCore = Join-Path $PSScriptRoot "antigravity_unlock.py"

$Host.UI.RawUI.ForegroundColor = 'Cyan'
Write-Host "===================================================================="
Write-Host "                  Antigravity CLI Unlocker v2.3.0                   "
Write-Host "     Обход региональных ограничений, фиксация 1.1.9 & автозапуск    "
Write-Host "===================================================================="
$Host.UI.RawUI.ForegroundColor = 'Gray'
Write-Host ""

$DnsPrimary = "111.88.96.50"
$DnsSecondary = "111.88.96.51"

function Show-IssuesHelp {
    Write-Host "`n Поддержка и решение проблем:" -ForegroundColor Yellow
    Write-Host "   $IssuesUrl`n" -ForegroundColor Cyan
}

function Invoke-PythonCore {
    param ([string[]]$ScriptArgs)

    if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command python3 -ErrorAction SilentlyContinue)) {
        Write-Host "[ОШИБКА] Интерпретатор Python не найден в системе." -ForegroundColor Red
        Show-IssuesHelp
        exit 1
    }

    if (-not (Test-Path $PythonCore)) {
        Write-Host "[ОШИБКА] Модуль ядра '$PythonCore' не найден." -ForegroundColor Red
        Show-IssuesHelp
        exit 1
    }

    $py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
    & $py $PythonCore $ScriptArgs
}

# ── Автозапуск / Guardian / Pin / Status ─────────────────
if ($Autostart) {
    Write-Host "[!] Установка автозапуска Guardian daemon..." -ForegroundColor Yellow
    Invoke-PythonCore -ScriptArgs @("autostart", "install")
    exit 0
}

if ($RemoveAutostart) {
    Write-Host "[!] Удаление автозапуска Guardian daemon..." -ForegroundColor Yellow
    Invoke-PythonCore -ScriptArgs @("autostart", "remove")
    exit 0
}

if ($Guardian) {
    Invoke-PythonCore -ScriptArgs @("guardian")
    exit 0
}

if ($PinInit) {
    Invoke-PythonCore -ScriptArgs @("pin", "init")
    exit 0
}

if ($PinCheck) {
    Invoke-PythonCore -ScriptArgs @("pin", "check")
    exit 0
}

if ($Status) {
    Invoke-PythonCore -ScriptArgs @("status")
    exit 0
}

# ── Откат изменений ─────────────────────────────────────────────────────
if ($Restore) {
    Write-Host "[!] Запуск восстановления через Python Core..." -ForegroundColor Yellow
    Invoke-PythonCore -ScriptArgs @("restore")

    try {
        $DefaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
        if ($DefaultRoute) {
            $Adapter = Get-NetAdapter | Where-Object InterfaceIndex -eq $DefaultRoute.InterfaceIndex
            if ($Adapter) {
                Set-DnsClientServerAddress -InterfaceIndex $Adapter.InterfaceIndex -ResetServerAddresses
                Write-Host "[ОК] Настройки DNS-серверов сброшены к значениям по умолчанию (DHCP) для '$($Adapter.Name)'." -ForegroundColor Green
            }
        }
    } catch {
        Write-Host "[ВНИМАНИЕ] Для сброса DNS перезапустите скрипт от имени администратора." -ForegroundColor Yellow
    }

    ipconfig /flushdns | Out-Null
    Write-Host "[ОК] Восстановление системы завершено." -ForegroundColor Green
    exit 0
}

# ── ШАГ 1: Обработка бинарника agy.exe через Python-модуль ─────────────
Write-Host "[1/2] Обработка бинарника и фиксация версии 1.1.9..." -ForegroundColor Magenta
$PyArgs = @()
if ($DryRun) { $PyArgs += "--dry-run" }
if ($Force)  { $PyArgs += "--force" }

Invoke-PythonCore -ScriptArgs $PyArgs

# ── ШАГ 2: Настройка DNS на интерфейсе по умолчанию ──────────────
Write-Host "`n[2/2] Настройка системной DNS-маршрутизации..." -ForegroundColor Magenta

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "  [ВНИМАНИЕ] Для настройки DNS необходимы права администратора." -ForegroundColor Yellow
    Write-Host "  [ИНФО] Перезапустите PowerShell от имени администратора." -ForegroundColor Yellow
} else {
    try {
        $DefaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
        if ($DefaultRoute) {
            $Adapter = Get-NetAdapter | Where-Object InterfaceIndex -eq $DefaultRoute.InterfaceIndex
            if ($Adapter) {
                Set-DnsClientServerAddress -InterfaceIndex $Adapter.InterfaceIndex -ServerAddresses ($DnsPrimary, $DnsSecondary)
                Write-Host "  [ОК] Серверы DNS ($DnsPrimary, $DnsSecondary) применены к активному интерфейсу: $($Adapter.Name)" -ForegroundColor Green
                ipconfig /flushdns | Out-Null
                Write-Host "  [ОК] Кэш DNS успешно очищен." -ForegroundColor Green
            } else {
                Write-Host "  [ВНИМАНИЕ] Адаптер для активного маршрута не найден." -ForegroundColor Yellow
            }
        } else {
            Write-Host "  [ВНИМАНИЕ] Активный маршрут по умолчанию (0.0.0.0/0) не обнаружен." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [ОШИБКА] Ошибка при установке DNS-серверов: $_" -ForegroundColor Red
        Show-IssuesHelp
    }
}

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "             Разблокировка Antigravity CLI завершена                " -ForegroundColor Green
Write-Host "====================================================================`n" -ForegroundColor Green
Write-Host "  Запуск:         agy" -ForegroundColor White
Write-Host "  Автозапуск:     .\antigravity_unlock_windows.ps1 -Autostart" -ForegroundColor Gray
Write-Host "  Удаление авто:  .\antigravity_unlock_windows.ps1 -RemoveAutostart" -ForegroundColor Gray
Write-Host "  Откат:          .\antigravity_unlock_windows.ps1 -Restore" -ForegroundColor Gray
Write-Host "  Тест:           .\antigravity_unlock_windows.ps1 -DryRun" -ForegroundColor Gray
Write-Host "  Поддержка:      $IssuesUrl" -ForegroundColor Cyan
