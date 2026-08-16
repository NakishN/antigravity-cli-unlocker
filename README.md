# Antigravity CLI Unlocker

Antigravity CLI Unlocker — кроссплатформенный инструментарий для обхода региональных ограничений, фиксации целевой версии (`1.1.9`) и автоматической настройки DNS-маршрутизации для **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на операционных системах Linux, macOS и Windows без использования VPN.

---

## Описание проекта

В регионах с ограничениями прямой доступ к эндпоинтам Google Generative AI (`generativelanguage.googleapis.com`) и сервисам авторизации блокируется на уровне граничных маршрутизаторов, а автоматические обновления `agy` могут приводить к поломкам патчей. Antigravity CLI Unlocker решает эти проблемы следующими механизмами:

1. **Фиксация версии (Version Pinning 1.1.9)**: Создает эталонный бэкап стабильной версии `1.1.9` (`agy.pinned.bak`), контролирует совпадение хэшей SHA-256 и размера файла и автоматически возвращает бинарник к версии `1.1.9` при попытках автоматического обновления.
2. **Фоновый демон Guardian**: Отслеживает бинарник `agy` с помощью таймера (каждые 30 секунд) и файловых событий (`watchdog`) и мгновенно восстанавливает версию `1.1.9` с перепатчиванием.
3. **Кроссплатформенный автозапуск (Autostart)**: Автоматическая регистрация демона Guardian в службах автозапуска операционной системы: `systemd` (Linux), `Task Scheduler / schtasks` (Windows), `launchd` (macOS).
4. **Патч региональных проверок (Eligibility Gate)**: Автоматический байпас внутренних геолокационных проверок в исполняемом файле `agy` / `agy.exe`.
5. **Системная DNS-маршрутизация и Split-Tunnel Proxy**: Направление доменных имен Google API через специализированные DNS-шлюзы (`111.88.96.50` / `111.88.96.51`) или через локальный прокси (`run` режим) без затрагивания авторизации `accounts.google.com`.

---

## Основные возможности

| Параметр | Значение |
| :--- | :--- |
| **Поддерживаемые ОС** | Ubuntu 24.04+, Debian, Arch Linux, Fedora, macOS, Windows 10, Windows 11 |
| **Фиксация версии** | Защита от автообновления, удерживает `1.1.9` с автопатчингом |
| **Автозапуск** | `systemd user unit` (Linux), `Task Scheduler` (Windows), `launchd` (macOS) |
| **Требования к сети** | Использование VPN не требуется |
| **Безопасность** | Проверка SHA256, резервные копии (`.original.bak`, `.pinned.bak`), `--dry-run`, `--restore` |

---

## Установка и автозапуск

### 1. Автозапуск и фиксация 1.1.9 (Рекомендуется)

#### Linux
```bash
./antigravity_unlock_linux.sh --autostart
```

#### macOS
```bash
chmod +x antigravity_unlock_macos.sh
./antigravity_unlock_macos.sh --autostart
```

#### Windows (PowerShell / Batch)
```powershell
.\antigravity_unlock_windows.ps1 -Autostart
```
*Или запустите `antigravity_unlock_windows.bat` от имени Администратора.*

---

## CLI Команды (`antigravity-unlock` / `antigravity_unlock.py`)

Проект предоставляет единый интерфейс командной строки:

```bash
# Проверить статус системы, бинарников agy, закрепленной версии и службы автозапуска
python3 antigravity_unlock.py status

# Установить службу автозапуска Guardian
python3 antigravity_unlock.py autostart install

# Проверить статус автозапуска
python3 antigravity_unlock.py autostart status

# Удалить службу автозапуска
python3 antigravity_unlock.py autostart remove

# Инициализировать фиксацию версии 1.1.9
python3 antigravity_unlock.py pin init

# Принудительно проверить и вернуть версию 1.1.9 при необходимости
python3 antigravity_unlock.py pin check

# Запустить фоновый демон Guardian в переднем плане
python3 antigravity_unlock.py guardian

# Запустить agy через локальный Split-Tunnel прокси
python3 antigravity_unlock.py run -- agy login
```

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
> Телеграмм группа проекта: https://t.me/NakishN

---

## Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
