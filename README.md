# Antigravity CLI Unlocker

Antigravity CLI Unlocker — инструментарий для обхода региональных ограничений и автоматической настройки DNS-маршрутизации для **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на операционных системах Linux, macOS и Windows без использования VPN.

---

## Описание проекта

В регионах с ограничениями прямой доступ к эндпоинтам Google Generative AI (`generativelanguage.googleapis.com`) и сервисам авторизации блокируется на уровне граничных маршрутизаторов. Antigravity CLI Unlocker решает эту проблему следующими механизмами:

1. **Патч региональных проверок (Eligibility Gate)**: Снятие внутренних геолокационных проверок в исполняемом файле `agy` / `agy.exe` (для архитектур x64 и ARM64).
2. **Системная DNS-маршрутизация и Split-Tunnel Proxy**: Направление доменных имен Google API через специализированные DNS-шлюзы (`111.88.96.50` / `111.88.96.51`) или через изолированный локальный прокси (`run-wrapped` режим) без затрагивания сервисов авторизации `accounts.google.com`.

---

## Основные возможности

| Параметр | Значение |
| :--- | :--- |
| **Поддерживаемые ОС** | Ubuntu 24.04, Debian, Arch Linux, Fedora, macOS, Windows 10, Windows 11 |
| **Поддерживаемые компоненты** | Antigravity CLI (`agy`), Antigravity IDE, Antigravity 2.0 |
| **Требования к сети** | Использование VPN не требуется |
| **Готовые релизы** | Готовые бинарники `.AppImage` (Linux), `.exe` (Windows), автономные исполняемые файлы |
| **Безопасность** | Вычисление SHA256, авто-бэкап бинарника перед патчем, аргумент `--dry-run`, команда отката (`--restore`) |

---

## Установка и запуск

### Вариант 1: Использование готовых релизов (.AppImage / .exe)

Скачайте релиз со страницы **[GitHub Releases](https://github.com/NakishN/antigravity-cli-unlocker/releases)**:

#### Linux (.AppImage / бинарник)
```bash
chmod +x Antigravity_Unlocker-x86_64.AppImage
./Antigravity_Unlocker-x86_64.AppImage run -- agy login
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
./antigravity_unlock_linux.sh
```

##### Дополнительные аргументы:
- `run -- agy <команда>`: Запустить `agy` с изолированным Split-Tunnel прокси.
- `--dry-run`: Выполнить проверку и расчет SHA-256 без внесения физических изменений в файл.
- `--force`: Принудительно выполнить патч даже при неизвестном хэше.
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
.\antigravity_unlock_windows.ps1
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

### Linux / macOS
```bash
./antigravity_unlock_linux.sh --restore
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

---

## Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
