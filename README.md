# Antigravity CLI Unlocker

Antigravity CLI Unlocker — инструментарий для обхода региональных ограничений и автоматической настройки DNS-маршрутизации для **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на операционных системах Linux и Windows без использования VPN.

---

## Описание проекта

В регионах с ограничениями прямой доступ к эндпоинтам Google Generative AI (`generativelanguage.googleapis.com`) и сервисам авторизации блокируется на уровне граничных маршрутизаторов. Antigravity CLI Unlocker решает эту проблему следующими механизмами:

1. **Патч региональных проверок (Eligibility Gate)**: Снятие внутренних геолокационных проверок в исполняемом файле `agy` / `agy.exe` (для архитектур x64 и ARM64).
2. **Системная DNS-маршрутизация**: Направление доменных имен Google API через специализированные DNS-шлюзы (`111.88.96.50` / `111.88.96.51`).

---

## Основные возможности

| Параметр | Значение |
| :--- | :--- |
| **Поддерживаемые ОС** | Ubuntu 24.04, Debian, Arch Linux, Fedora, Windows 10, Windows 11 |
| **Поддерживаемые компоненты** | Antigravity CLI (`agy`), Antigravity IDE, Antigravity 2.0 |
| **Требования к сети** | Использование VPN не требуется |
| **Безопасность** | Автоматический бэкап бинарного файла перед патчем, команда отката (`--restore`) |

---

## Установка и запуск

### Linux (Ubuntu / Debian / Arch)

Выполните команду установки:

```bash
git clone https://github.com/NakishN/antigravity-cli-unlocker.git
cd antigravity-cli-unlocker
chmod +x antigravity_unlock_linux.sh
./antigravity_unlock_linux.sh
```

#### Автоматические действия скрипта:
- Авто-поиск исполняемого файла `agy` (`~/.local/bin/agy` или `/usr/local/bin/agy`).
- Создание резервной копии по пути `~/.local/share/antigravity-unlocker/agy.original.bak`.
- Применение машинных патчей для затворов eligibility gate (x64 и ARM64).
- Создание конфигурации `systemd-resolved` (`/etc/systemd/resolved.conf.d/antigravity-unlock.conf`) для маршрутизации DNS-запросов Google API.

---

### Windows (10 / 11)

#### Способ 1: Запуск bat-файла (Рекомендуется)
1. Скачайте или клонируйте репозиторий.
2. Нажмите правой кнопкой мыши по файлу **`antigravity_unlock_windows.bat`** и выберите **«Запуск от имени администратора»**.

#### Способ 2: Запуск через PowerShell (Администратор)
Откройте PowerShell от имени администратора и выполните:

```powershell
Set-ExecutionPolicy Unrestricted -Scope Process -Force
.\antigravity_unlock_windows.ps1
```

---

## Откат изменений (Восстановление)

Для полного восстановления оригинального файла `agy` и сброса сетевых настроек DNS:

### Linux
```bash
./antigravity_unlock_linux.sh --restore
```

### Windows
```powershell
.\antigravity_unlock_windows.ps1 -Restore
```

---

## Техническая интеграция и совместимость

### Совместимость с Antigravity IDE и Antigravity 2.0
Системная настройка DNS (`systemd-resolved` в Linux или свойства сетевого адаптера в Windows) действует глобально на все сетевые контексты Electron и Chromium, используемые приложениями Antigravity IDE и Antigravity 2.0. Дополнительная настройка графических приложений не требуется.

### Повторное применение после обновлений
При обновлении CLI командой `agy update` Google заменяет исполняемый файл. После любого обновления необходимо повторно запустить скрипт разблокировки.

---

## Поддержка и решение проблем

При возникновении ошибок или вопросов при установке и использовании:

> [!NOTE]
> Вы можете создать обращение в разделе [GitHub Issues](https://github.com/NakishN/antigravity-cli-unlocker/issues).

При создании обращения укажите следующую информацию:
- Версия операционной системы (`lsb_release -a` или `winver`)
- Версия Antigravity CLI (`agy --version`)
- Полный текст ошибки из консоли

---

## Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
