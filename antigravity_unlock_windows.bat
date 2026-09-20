@echo off
:: Antigravity CLI Unlocker v1.5.0 (Windows Batch Launcher)
:: Запуск PowerShell-скрипта БЕЗ запроса прав Администратора.
::
:: Права администратора больше не нужны: в 1.5.0 удалён шаг, который менял
:: системный DNS через Set-DnsClientServerAddress.  Теперь скрипт правит только
:: agy.exe в каталоге пользователя.
::
:: Прежняя версия к тому же теряла аргументы: при перезапуске через
:: "Start-Process '%~f0' -Verb RunAs" параметры командной строки не
:: передавались в elevated-копию, поэтому -DryRun/-Restore молча игнорировались.

chcp 65001 >nul
title Antigravity CLI Unlocker v1.5.0

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0antigravity_unlock_windows.ps1" %*

echo.
pause
