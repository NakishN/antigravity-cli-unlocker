@echo off
:: Antigravity CLI Unlocker v2.2.0 (Windows Batch Launcher)
:: Запуск PowerShell-скрипта с запросом прав Администратора

chcp 65001 >nul
title Antigravity CLI Unlocker v2.2.0

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo  [!] Запрос прав Администратора...
    echo.
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0antigravity_unlock_windows.ps1" %*

echo.
pause
