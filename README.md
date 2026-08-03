# 🚀 Google Antigravity CLI Unlocker (Linux & Windows)

![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![AGY Version](https://img.shields.io/badge/Antigravity_CLI-v1.x--v2.x-brightgreen)
![No VPN Required](https://img.shields.io/badge/VPN-Not_Required-orange)

Инструмент для разблокировки и полноценного использования **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** без использования VPN в регионах с ограничениями (РФ и РБ).

---

## ⚡ Особенности и возможности

- 🔓 **Работа без VPN**: Запросы к `generativelanguage.googleapis.com` и авторизации Google перенаправляются через проверенные маршруты Smart DNS (`111.88.96.50` / `111.88.96.51`).
- 🛠 **Патч регионального блока (Eligibility Gate)**: Автоматическое снятие геоблока в бинарном коде `agy` / `agy.exe` (x64 и ARM64).
- 💾 **Автоматический бэкап**: Перед внесением изменений всегда создается резервная копия оригинального бинарника.
- 🔄 **Безопасный откат (`--restore`)**: Возможность мгновенно отменить все изменения и вернуть систему в исходное состояние одной командой.
- 💻 **Кроссплатформенность**: Поддержка **Ubuntu 24.04 / Debian / Arch / Fedora** и **Windows 10 / 11**.

---

## 🐧 Инструкция по установке на Linux (Ubuntu / Debian / Arch)

### Быстрый запуск в 1 команду:

```bash
git clone https://github.com/USERNAME/antigravity-cli-unlocker.git
cd antigravity-cli-unlocker
chmod +x antigravity_unlock_linux.sh
./antigravity_unlock_linux.sh
```

### Что делает скрипт на Linux:
1. Автоматически находит исполняемый файл `agy` в `~/.local/bin/agy` или `/usr/local/bin/agy`.
2. Создает резервную копию в `~/.local/share/antigravity-unlocker/agy.original.bak`.
3. Применяет бинарный патч снимка x64 / ARM64.
4. Настраивает `systemd-resolved` (`/etc/systemd/resolved.conf.d/antigravity-unlock.conf`) для прозрачной маршрутизации доменов Google через Smart DNS.

---

## 🪟 Инструкция по установке на Windows (10 / 11)

### Способ 1 (через Batch-файловый запуск):
1. Скачайте репозиторий (или файлы `antigravity_unlock_windows.bat` и `antigravity_unlock_windows.ps1`).
2. Нажмите правой кнопкой мыши по **`antigravity_unlock_windows.bat`** ➔ **«Запуск от имени Администратора»**.
3. Скрипт сам выполнит бэкап, патч `agy.exe` и применит настройки DNS.

### Способ 2 (через PowerShell):
Откройте **PowerShell от имени Администратора** и выполните:

```powershell
Set-ExecutionPolicy Unrestricted -Scope Process -Force
.\antigravity_unlock_windows.ps1
```

---

## 🔄 Как откатить изменения (Restore / Uninstall)

Если вы хотите вернуть оригинальный файл `agy` и стандартные настройки DNS:

### На Linux:
```bash
./antigravity_unlock_linux.sh --restore
```

### На Windows:
```powershell
.\antigravity_unlock_windows.ps1 -Restore
```

---

## ❓ Часто задаваемые вопросы (FAQ)

### 1. Будет ли это работать с обычными версии Antigravity (IDE / Antigravity 2.0)?
**Да, 100%!**
- **Antigravity CLI (`agy`)**: Разблокируется полностью — поддерживаются все модели (Claude 3.7 Sonnet / Gemini 3.6 Flash / Pro), вызов подагентов, фоновые задачи, генерация артефактов и инструментов.
- **Antigravity IDE и Antigravity 2.0 (Desktop App)**: Так как Antigravity IDE использует системный стек сетевых запросов и Electron, установленные правила Smart DNS на уровне системы (`systemd-resolved` в Linux или сетевой адаптер в Windows) автоматически перенаправляют соединения IDE и приложения 2.0 к серверам Google API без блокировок.

### 2. Что делать после обновления `agy`?
При обновлении `agy` бинарник перезаписывается чистой версией от Google. Просто запустите скрипт разблокировки заново.

---

## 📜 Лицензия
Проект распространяется под открытой лицензией [MIT](LICENSE).
