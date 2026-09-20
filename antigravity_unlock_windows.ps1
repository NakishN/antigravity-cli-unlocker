# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v1.5.0                     ║
# ║     Патч eligibility-гейта, диагностика & автозапуск (Windows)       ║
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
    [switch]$Status,
    [switch]$Doctor,
    [switch]$CleanupLegacy
)

$Version = "1.5.0"
$IssuesUrl = "https://github.com/NakishN/antigravity-cli-unlocker/issues"
$PythonCore = Join-Path $PSScriptRoot "antigravity_unlock.py"

$Host.UI.RawUI.ForegroundColor = 'Cyan'
Write-Host "===================================================================="
Write-Host "                  Antigravity CLI Unlocker v$Version                  "
Write-Host "     Патч eligibility-гейта, диагностика и защита от автообновлений  "
Write-Host "===================================================================="
$Host.UI.RawUI.ForegroundColor = 'Gray'
Write-Host ""

# ── Удалено в 1.5.0 ────────────────────────────────────────────────────────
# Раньше ШАГ 2 прописывал Smart DNS (xbox-dns.ru, 111.88.96.50/51) на активный
# сетевой интерфейс через Set-DnsClientServerAddress, то есть менял DNS всей
# системе и требовал прав администратора.  Проверка 2026-09-20 показала, что эти
# резолверы возвращают для cloudcode-pa.googleapis.com те же реальные IP Google,
# что и 8.8.8.8 — подмены нет, шаг не давал ничего, кроме побочных эффектов.
#
# Eligibility-гейт — клиентская проверка серверного protobuf-поля, и её снимает
# патч бинарника.  Проверено на agy 1.2.7 из заблокированного региона без VPN,
# прокси и подмены DNS: `agy -p` возвращает реальные ответы модели.
#
# Reset-LegacyDns ниже СОХРАНЁН намеренно: у тех, кто запускал прежние версии,
# DNS интерфейса уже изменён, и его надо уметь вернуть.
# ───────────────────────────────────────────────────────────────────────────

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

function Get-DefaultAdapter {
    try {
        $DefaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
            Sort-Object RouteMetric | Select-Object -First 1
        if ($DefaultRoute) {
            return Get-NetAdapter | Where-Object InterfaceIndex -eq $DefaultRoute.InterfaceIndex
        }
    } catch { }
    return $null
}

function Get-LegacyDnsState {
    <#
        Возвращает @{ Adapter; IsLegacy } без каких-либо изменений системы.
        IsLegacy - $true, только если на адаптере действительно стоят адреса
        xbox-dns.ru, прописанные прежними версиями.
    #>
    $Result = @{ Adapter = $null; IsLegacy = $false }
    $Adapter = Get-DefaultAdapter
    if (-not $Adapter) { return $Result }
    $Result.Adapter = $Adapter

    try {
        $DnsArgs = @{
            InterfaceIndex = $Adapter.InterfaceIndex
            AddressFamily  = "IPv4"
            ErrorAction    = "SilentlyContinue"
        }
        $Current = (Get-DnsClientServerAddress @DnsArgs).ServerAddresses
    } catch { $Current = @() }

    $Legacy = @("111.88.96.50", "111.88.96.51")
    $Result.IsLegacy = @($Current | Where-Object { $Legacy -contains $_ }).Count -gt 0
    return $Result
}

function Report-LegacySettings {
    # Только чтение: основной сценарий разблокировки не должен требовать
    # администратора.  Удаление - за явным -CleanupLegacy или -Restore.
    $State = Get-LegacyDnsState
    $Found = $false

    if ($State.IsLegacy) {
        Write-Host "  [ВНИМАНИЕ] На адаптере '$($State.Adapter.Name)' прописан Smart DNS (xbox-dns.ru) версиями <=1.4.x." -ForegroundColor Yellow
        $Found = $true
    }

    $Hosts = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
    if ((Test-Path $Hosts) -and (Select-String -Path $Hosts -Pattern "cloudcode-pa\.googleapis\.com|generativelanguage\.googleapis\.com" -ErrorAction SilentlyContinue)) {
        Write-Host "  [ВНИМАНИЕ] В hosts найдены устаревшие пины CloudCode." -ForegroundColor Yellow
        $Found = $true
    }

    if ($Found) {
        Write-Host ""
        Write-Host "  Это настройки версий <=1.4.x. Они больше не нужны и могут мешать:" -ForegroundColor Yellow
        Write-Host "  Smart DNS не подменяет CloudCode, а пин в hosts указывает на" -ForegroundColor Yellow
        Write-Host "  эндпоинт, который не завершает TLS-рукопожатие." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  Удалить (потребуется PowerShell от администратора):" -ForegroundColor White
        Write-Host "    .\antigravity_unlock_windows.ps1 -CleanupLegacy" -ForegroundColor Gray
        Write-Host "    python `"$PythonCore`" setup remove" -ForegroundColor Gray
        Write-Host ""
    }
}

function Reset-LegacyDns {
    <#
        Возвращает DNS интерфейса к DHCP, если прежние версии скрипта
        прописали туда Smart DNS.  Ничего не трогает, если подмены не было.
    #>
    $State = Get-LegacyDnsState
    if (-not $State.Adapter) {
        Write-Host "  [ИНФО] Активный сетевой адаптер не найден - сброс DNS пропущен." -ForegroundColor Yellow
        return
    }
    if (-not $State.IsLegacy) {
        Write-Host "  [ИНФО] DNS адаптера '$($State.Adapter.Name)' не менялся этим инструментом - сброс не нужен." -ForegroundColor Yellow
        return
    }

    try {
        Set-DnsClientServerAddress -InterfaceIndex $State.Adapter.InterfaceIndex -ResetServerAddresses
        ipconfig /flushdns | Out-Null
        Write-Host "  [ОК] Smart DNS (xbox-dns.ru) сброшен к DHCP на адаптере '$($State.Adapter.Name)'." -ForegroundColor Green
    } catch {
        Write-Host "  [ВНИМАНИЕ] Не удалось сбросить DNS: $_" -ForegroundColor Yellow
        Write-Host "  [ИНФО] Перезапустите PowerShell от имени администратора." -ForegroundColor Yellow
    }
}

function Show-HostsHint {
    $Hosts = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
    if (Test-Path $Hosts) {
        if (Select-String -Path $Hosts -Pattern "cloudcode-pa\.googleapis\.com|generativelanguage\.googleapis\.com" `
                          -ErrorAction SilentlyContinue) {
            Write-Host "  [ИНФО] В $Hosts найдены устаревшие пины (версии <=1.4.x)." -ForegroundColor Yellow
            Write-Host "         Удалите их вручную от имени администратора либо командой:" -ForegroundColor Yellow
            Write-Host "           python `"$PythonCore`" setup remove" -ForegroundColor White
        }
    }
}

# ── Автозапуск / Guardian / Pin / Status / Doctor ─────────────────
if ($Autostart) {
    Write-Host "[!] Установка автозапуска Guardian daemon..." -ForegroundColor Yellow
    Invoke-PythonCore -ScriptArgs @("autostart", "install")
    Write-Host "[ОК] Guardian будет перепатчивать agy после каждого автообновления." -ForegroundColor Green
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

if ($Doctor) {
    Invoke-PythonCore -ScriptArgs @("doctor")
    exit $LASTEXITCODE
}

if ($CleanupLegacy) {
    Write-Host "[!] Очистка настроек, оставленных версиями <=1.4.x..." -ForegroundColor Yellow
    Reset-LegacyDns
    Show-HostsHint
    exit 0
}

# ── Откат изменений ─────────────────────────────────────────────────────
if ($Restore) {
    Write-Host "[!] Запуск восстановления через Python Core..." -ForegroundColor Yellow
    Invoke-PythonCore -ScriptArgs @("restore")
    Reset-LegacyDns
    Show-HostsHint
    Write-Host "[ОК] Восстановление системы завершено." -ForegroundColor Green
    exit 0
}

# ── ЕДИНСТВЕННЫЙ ШАГ: патч бинарника agy.exe ────────────────────────────
Write-Host "[1/1] Патч установленного бинарника agy..." -ForegroundColor Magenta
$PyArgs = @()
if ($DryRun) { $PyArgs += "--dry-run" }
if ($Force)  { $PyArgs += "--force" }

Invoke-PythonCore -ScriptArgs $PyArgs

Write-Host "`n[+] Проверка устаревших настроек (<=1.4.x)..." -ForegroundColor Magenta
Report-LegacySettings

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "             Разблокировка Antigravity CLI завершена                " -ForegroundColor Green
Write-Host "====================================================================`n" -ForegroundColor Green
Write-Host "  Запуск:         agy" -ForegroundColor White
Write-Host "  Диагностика:    .\antigravity_unlock_windows.ps1 -Doctor" -ForegroundColor Gray
Write-Host "  Автозапуск:     .\antigravity_unlock_windows.ps1 -Autostart" -ForegroundColor Gray
Write-Host "  Удаление авто:  .\antigravity_unlock_windows.ps1 -RemoveAutostart" -ForegroundColor Gray
Write-Host "  Откат:          .\antigravity_unlock_windows.ps1 -Restore" -ForegroundColor Gray
Write-Host "  Тест:           .\antigravity_unlock_windows.ps1 -DryRun" -ForegroundColor Gray
Write-Host "  Поддержка:      $IssuesUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [!] agy самообновляется и затирает патч. Установите автозапуск:" -ForegroundColor Yellow
Write-Host "        .\antigravity_unlock_windows.ps1 -Autostart" -ForegroundColor White
Write-Host ""
