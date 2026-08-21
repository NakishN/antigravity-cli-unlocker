# Antigravity CLI Unlocker

Antigravity CLI Unlocker — инструментарий для обхода региональных ограничений, гибкого управления стратегиями патча (`auto`, `in_place`, `pin 1.1.9`) и настройки DNS-маршрутизации для **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на операционных системах Linux, macOS и Windows без использования VPN.

---

## Описание проекта

В регионах с ограничениями прямой доступ к эндпоинтам Google Generative AI (`generativelanguage.googleapis.com`) и сервисам авторизации блокируется на уровне граничных маршрутизаторов, а автообновления `agy` могут ломать рабочий патч. Antigravity CLI Unlocker решает эту проблему следующими механизмами:

1. **Патч региональных проверок (Eligibility Gate)**: Снятие внутренних проверок доступности аккаунта и геолокации в исполняемом файле `agy` / `agy.exe`. Включает прямое патчирование машинного кода в секции `.text` для версий `1.1.17+` (`EligibilityError`, `IneligibilityFromResult`) и байт-патчинг дескрипторов для ранних версий (`1.1.9`).
2. **Стратегии разблокировки (Patch Strategies)**:
   - **`auto` (по умолчанию)**: Патчит текущую установленную версию на месте. Если сигнатуры новой версии не поддерживаются, автоматически откатывает бинарник к проверенной стабильной версии `1.1.9`.
   - **`in_place`**: Патчит только текущую установленную версию бинарника прямо на месте без отката и даунгрейда.
   - **`pin`**: Принудительно откатывает и фиксирует стабильную версию `1.1.9` с защитой от перезаписи.
3. **Системная DNS-маршрутизация и Split-Tunnel Proxy**: Направление доменных имен Google API через специализированные DNS-шлюзы (`111.88.96.50` / `111.88.96.51`) или через изолированный локальный прокси (`run` режим) без затрагивания сервисов авторизации `accounts.google.com`.
4. **Фоновый контроль целостности (Guardian & Autostart)**: Защита от автообновлений `agy`. Демон Guardian отслеживает изменения бинарника и применяет активную стратегию (`auto`, `in_place` или `pin`).

---

## Основные возможности

| Параметр | Значение |
| :--- | :--- |
| **Поддерживаемые ОС** | Ubuntu 24.04+, Debian, Arch Linux, Fedora, macOS, Windows 10, Windows 11 |
| **Поддерживаемые компоненты** | Antigravity CLI (`agy`), Antigravity IDE, Antigravity 2.0 |
| **Поддерживаемые версии CLI** | `1.1.9`, `1.1.16`, `1.1.17+` (включая машинный патч Go-рантайма) |
| **Стратегии работы** | `auto` (in-place + fallback), `in_place` (только текущая), `pin` (фиксация 1.1.9) |
| **Автозапуск Guardian** | `systemd user unit` (Linux), `Task Scheduler` (Windows), `launchd` (macOS) |
| **Требования к сети** | Использование VPN не требуется |
| **Готовые релизы** | Готовые бинарники `.AppImage` (Linux), `.exe` (Windows), автономные исполняемые файлы |
| **Безопасность** | Вычисление SHA256, резервные копии (`.original.bak`, `.pinned.bak`), `--dry-run`, `--restore` |

---

## Установка и запуск

### Вариант 1: Использование готовых релизов (.AppImage / .exe)

Скачайте релиз со страницы **[GitHub Releases](https://github.com/NakishN/antigravity-cli-unlocker/releases)**:

#### Linux (.AppImage / бинарник)
```bash
chmod +x Antigravity_Unlocker-x86_64.AppImage

# Запуск с авто-патчем текущей версии или откатом на 1.1.9
./Antigravity_Unlocker-x86_64.AppImage run -- agy login

# Запуск с явным указанием стратегии
./Antigravity_Unlocker-x86_64.AppImage run --strategy in_place -- agy login
./Antigravity_Unlocker-x86_64.AppImage run --strategy pin -- agy login
```

#### Windows (.exe)
```powershell
.\antigravity-unlock-windows-x64.exe run -- agy login
```

---

### Вариант 2: Запуск из исходников

#### Linux & macOS

Выполните команду установки:

```bash
git clone https://github.com/NakishN/antigravity-cli-unlocker.git
cd antigravity-cli-unlocker
chmod +x antigravity_unlock_linux.sh

# Стандартная разблокировка (стратегия auto)
./antigravity_unlock_linux.sh

# Разблокировка с включением автозапуска службы Guardian
./antigravity_unlock_linux.sh --autostart
```

Для **macOS** используйте скрипт `antigravity_unlock_macos.sh`:
```bash
chmod +x antigravity_unlock_macos.sh
./antigravity_unlock_macos.sh --autostart
```

##### Дополнительные команды и аргументы:
- `--strategy {auto,in_place,pin}`: Выбор стратегии патча (по умолчанию `auto`).
- `pin strategy <auto|in_place|pin>`: Сохранить выбранную стратегию по умолчанию в конфигурации.
- `--autostart`: Установить фоновую службу Guardian в автозапуск.
- `--remove-autostart`: Удалить службу автозапуска Guardian.
- `run -- agy <команда>`: Запустить `agy` с изолированным Split-Tunnel прокси.
- `--dry-run`: Выполнить проверку без внесения изменений.
- `--force`: Принудительно выполнить патч.
- `--restore`: Восстановить исходный бинарник из резервной копии.

---

### Windows (10 / 11)

#### Способ 1: Запуск bat-файла (Рекомендуется)
1. Скачайте или клонируйте репозиторий.
2. Нажмите правой кнопкой мыши по файлу **`antigravity_unlock_windows.bat`** и выберите **«Запуск от имени администратора»**.

#### Способ 2: Запуск через PowerShell (Администратор)
Откройте PowerShell от имени администратора и выполните:

```powershell
Set-ExecutionPolicy Unrestricted -Scope Process -Force

# Стандартный запуск
.\antigravity_unlock_windows.ps1

# Запуск с включением автозапуска Guardian
.\antigravity_unlock_windows.ps1 -Autostart
```

---

## Безопасность и архитектура DNS

### Уведомление о DNS-серверах и прокси
По умолчанию система настраивает маршрутизацию доменов `generativelanguage.googleapis.com` через проверенные публичные серверы сообщества Smart DNS (`111.88.96.50` / `111.88.96.51`) или локальный прокси. При этом трафик авторизации `accounts.google.com` пускается напрямую (DIRECT) для предотвращения любых рисков безопасности.

- На **Linux** под управлением `systemd-resolved` создается отдельный изолированный файл правил `/etc/systemd/resolved.conf.d/antigravity-unlock.conf`.
- На **Windows** определяется активный сетевой маршрут по умолчанию (`Get-NetRoute -DestinationPrefix "0.0.0.0/0"`).
- Логи работы сохраняются в системный файл: `~/.local/share/antigravity-unlocker/unlocker.log`.

---

## Откат изменений (Восстановление)

Для полного восстановления оригинального файла `agy` и сброса сетевых настроек DNS:

### Linux
```bash
./antigravity_unlock_linux.sh --restore
```

### macOS
```bash
./antigravity_unlock_macos.sh --restore
```

### Windows
```powershell
.\antigravity_unlock_windows.ps1 -Restore
```

---

## Поддержка и решение проблем

При возникновении ошибок или вопросов при установке и использовании:

> [!NOTE]
> Вы можете создать обращение в разделе [GitHub Issues](https://github.com/NakishN/antigravity-cli-unlocker/issues).
> Также можете вступить в телеграм группу, где буду ещё многое публиковать https://t.me/NakishN

---

## Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
