# Antigravity CLI Unlocker

Antigravity CLI Unlocker — инструментарий для снятия региональной проверки доступности (Eligibility Gate) в **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на Linux, macOS и Windows: версионно-независимый патч бинарника, послойная диагностика (`doctor`) и фоновый Guardian, который перепатчивает `agy` после каждого автообновления.

---

## Описание проекта

`agy` показывает `Eligibility check failed: Your current account is not eligible for Antigravity, because it is not currently available in your location.` Эта проверка **клиентская**: сервер возвращает protobuf-поле `ineligible`, а клиент блокирует работу, если оно заполнено. Сам текст ошибки в бинарнике отсутствует — он приходит с сервера.

Инструмент решает задачу четырьмя механизмами:

1. **Патч eligibility-гейта (основной и достаточный)**. В бинарнике переименовывается строковый литерал `ineligible` → `inexigible` **той же длины**. Замена регистрозависимая и применяется ко всем вхождениям, поэтому:
   - сериализованный protobuf-дескриптор и Go struct-теги (`name=ineligible`, `json=ineligibleTiers`) переименовываются **согласованно**;
   - Go-идентификаторы (`IneligibleTier`, `IneligibleInfo`) **не затрагиваются** — бинарник продолжает линковаться;
   - серверный ключ `"ineligible"` в JSON больше не матчится ни на одно поле, гейт видит незаполненное поле и пропускает запрос;
   - длина всех замен одинакова, поэтому offsets, релокации и layout ELF/PE не меняются, а откат — побайтовый.

   Патч версионно-независим: он ищет литерал, а не машинный код и не смещения. Проверено на `agy 1.2.7` (9 вхождений, размер файла сохранён байт-в-байт).

2. **Честная классификация состояния**. Патчер различает три исхода, а не два:
   - `patched` — переименование применено;
   - `unpatched` — сигнатура на месте, патч ещё не применён;
   - `foreign` — **ни** сигнатуры, **ни** её замены нет: это незнакомая сборка. Такой бинарник **не трогается**, чтобы `agy` показал собственную ошибку и пользователь понял, что патчеру нужна новая сигнатура. Прежние версии отвечали «уже пропатчено» в обоих случаях, то есть молча врали.

3. **Стратегии патча**:
   - **`in_place` (по умолчанию с 1.5.0)**: патчит установленную версию на месте. Никаких откатов и даунгрейдов.
   - **`auto`**: то же, но может откатиться на закреплённую версию — **только** при явном `allow_pin_fallback=true` в конфиге.
   - **`pin`**: принудительно фиксирует закреплённую версию.

   Тихий даунгрейд убран: `agy` обновляется сам, и замена свежего бинарника на старый «потому что сигнатура не совпала» превращала «мы пока не умеем патчить эту сборку» в «у вас сломан `agy`».

4. **Guardian и автозапуск**. `agy` при самообновлении перезаписывает бинарник и затирает патч — именно так установка ломается сама по себе. Guardian отслеживает `size`/`mtime` бинарника, отличает «обновление затёрло патч» от «сборка незнакомая» и перепатчивает только в первом случае. Автозапуск: `systemd user unit` (Linux), `launchd` (macOS), `Task Scheduler` (Windows).

---

## Основные возможности

| Параметр | Значение |
| :--- | :--- |
| **Поддерживаемые ОС** | Ubuntu 24.04+, Debian, Arch Linux, Fedora, macOS, Windows 10, Windows 11 |
| **Поддерживаемые компоненты** | Antigravity CLI (`agy`), Antigravity IDE, Antigravity 2.0 |
| **Проверено на** | `agy 1.2.7` (Linux x86_64) — патч + реальные ответы модели. Ранее: `1.1.9`–`1.1.27` |
| **Совместимость** | Версионно-независимая: ищется строковый литерал, а не машинный код |
| **Стратегии работы** | `in_place` (по умолчанию), `auto` (in-place + опциональный откат), `pin` |
| **Диагностика** | `doctor` — 6 слоёв с живой проверкой `agy -p` в конце |
| **Автозапуск Guardian** | `systemd user unit` (Linux), `Task Scheduler` (Windows), `launchd` (macOS) |
| **Зависимости Python** | Отсутствуют (опционально `watchdog` для file-watch) |
| **Права root** | Не требуются (патчится бинарник в каталоге пользователя) |
| **Готовые релизы** | `.AppImage` (Linux), `.exe` (Windows), автономный бинарник (macOS) |
| **Безопасность** | SHA-256, резервные копии (`.original.bak`, `.pinned.bak`), `--dry-run`, `restore` |

---

## Быстрый старт

```bash
# 1. Пропатчить установленный agy
antigravity-unlock patch

# 2. Убедиться, что всё работает (последний слой реально запускает agy)
antigravity-unlock doctor

# 3. Защититься от автообновлений agy
antigravity-unlock autostart install
```

Шаг 3 не обязателен, но без него следующее автообновление `agy` снова затрёт патч.

---

## Установка и запуск

### Вариант 1: Использование готовых релизов (.AppImage / .exe)

Скачайте релиз со страницы **[GitHub Releases](https://github.com/NakishN/antigravity-cli-unlocker/releases)**:

#### Linux (.AppImage / бинарник)
```bash
chmod +x Antigravity_Unlocker-x86_64.AppImage

# Патч + диагностика
./Antigravity_Unlocker-x86_64.AppImage patch
./Antigravity_Unlocker-x86_64.AppImage doctor

# Пропатчить (если нужно) и сразу запустить agy
./Antigravity_Unlocker-x86_64.AppImage run -- agy login

# Явное указание стратегии
./Antigravity_Unlocker-x86_64.AppImage run --strategy in_place -- agy login
```

#### Windows (.exe)
```powershell
.\antigravity-unlock-windows-x64.exe patch
.\antigravity-unlock-windows-x64.exe doctor
.\antigravity-unlock-windows-x64.exe run -- agy login
```

---

### Вариант 2: Запуск из исходников

#### Linux & macOS

```bash
git clone https://github.com/NakishN/antigravity-cli-unlocker.git
cd antigravity-cli-unlocker
chmod +x antigravity_unlock_linux.sh

# Патч установленного agy (sudo не нужен)
./antigravity_unlock_linux.sh

# Диагностика по всем слоям
./antigravity_unlock_linux.sh --doctor

# Включить автозапуск Guardian (защита от автообновлений agy)
./antigravity_unlock_linux.sh --autostart
```

Для **macOS** используйте `antigravity_unlock_macos.sh`:
```bash
chmod +x antigravity_unlock_macos.sh
./antigravity_unlock_macos.sh --autostart
```

##### Команды и аргументы
| Команда | Назначение |
| :--- | :--- |
| `patch` | Применить патч к бинарнику на месте |
| `patch --dry-run` | Показать, что будет применено, без записи |
| `patch --include-optional` | Применить и opt-in паттерны (см. ниже) |
| `doctor` | Послойная диагностика; `--no-network`, `--no-functional`, `--json` |
| `status` | Бинарники, состояние патча, стратегия, автозапуск |
| `run -- agy <аргументы>` | Пропатчать при необходимости и передать терминал `agy` |
| `restore` | Восстановить исходный бинарник из резервной копии |
| `autostart install` / `remove` / `status` | Управление службой Guardian |
| `guardian` | Запустить Guardian в foreground |
| `pin strategy <in_place\|auto\|pin>` | Сохранить стратегию по умолчанию |
| `pin init` / `pin check` | Управление закреплённой версией |
| `ipv4 apply` / `remove` / `status` | Приоритет IPv4 над IPv6 |
| `endpoint apply` / `remove` / `status` | Переопределение CloudCode-эндпоинта для IDE |
| `setup remove` / `status` | Очистка `/etc/hosts`-пинов, оставленных версиями ≤1.4.x |

---

### Windows (10 / 11)

#### Способ 1: bat-файл
1. Скачайте или клонируйте репозиторий.
2. Запустите **`antigravity_unlock_windows.bat`**.

> [!NOTE]
> С 1.5.0 права администратора **не требуются** и не запрашиваются: удалён шаг, менявший системный DNS. Прежняя версия к тому же теряла аргументы при elevated-перезапуске, из-за чего `-DryRun` и `-Restore` молча игнорировались.

#### Способ 2: PowerShell
```powershell
Set-ExecutionPolicy Unrestricted -Scope Process -Force

.\antigravity_unlock_windows.ps1              # патч
.\antigravity_unlock_windows.ps1 -Doctor      # диагностика
.\antigravity_unlock_windows.ps1 -Autostart   # защита от автообновлений
```

---

## Диагностика: `antigravity-unlock doctor`

Ошибка «not available in your location» одинаково выглядит при совершенно разных причинах. `doctor` проверяет слои по отдельности и говорит, какой именно сломан, с готовой командой починки:

| Слой | Что проверяет |
| :--- | :--- |
| `binary` | Найден ли `agy`, его версия, состояние патча по сигнатурам, наличие бэкапа |
| `strategy` | Не попытается ли стратегия заменить свежий `agy` старым |
| `guardian` | Запущен ли Guardian и установлен ли автозапуск |
| `hosts pin` | Не остались ли в `/etc/hosts` пины от версий ≤1.4.x |
| `egress` | Публичный IP и страна выхода |
| `endpoint` | Достаёт ли запрос до настоящего CloudCode и **почему** он отказал |
| `functional` | Реальный запуск `agy -p` — единственный слой, который не догадывается |

Проверки только читают состояние и ограничены по времени; `functional` тратит один запрос к модели, поэтому отключается через `--no-functional`.

Пример вывода на реальной машине:

```
agy: /home/user/.local/bin/agy   version: 1.2.7
egress: 95.26.82.199 (RU, AS8402 PJSC Vimpelcom)

[ ok ] binary /home/user/.local/bin/agy
        agy 1.2.7 - patched (protobuf_ineligible_bare renamed (9x))
[ ok ] strategy
        strategy=in_place
[FAIL] hosts pin
        4 CloudCode pin line(s) left in /etc/hosts ...
        -> sudo antigravity-unlock setup remove
[ ok ] functional
        agy completed a real prompt end-to-end (exit 0): 'DOCTOR_OK'
```

---

## Как это работает на самом деле

Раздел написан потому, что прежние версии документировали механизм, который не работал.

**Eligibility-гейт обходит только патч бинарника.** Проверено 2026-09-20 на `agy 1.2.7`: после переименования 9 вхождений `ineligible` CLI отвечает на реальные запросы (`agy -p` → осмысленный ответ, `agy models` → полный список моделей), **с российского IP-адреса выхода, без VPN, прокси и подмены DNS**.

Что при этом оказалось бесполезным и удалено в 1.5.0:

- **Smart DNS (`xbox-dns.ru`, `comss.one`, `geohide.ru`)**. Замер `dig` показал: для `cloudcode-pa.googleapis.com` и `daily-cloudcode-pa.googleapis.com` эти резолверы возвращают **те же самые реальные IP Google** (`172.217.x.x`), что и `8.8.8.8`. Подмены нет. Подменялся только `generativelanguage.googleapis.com`, который `agy` не использует. При этом скрипты меняли системный DNS и требовали root/администратора.
- **SNI-прокси и пины в `/etc/hosts`**. Единственный IP (`45.155.204.190`, Москва, Cloud.ru) принимает TCP-соединение на 443, но **не завершает TLS-рукопожатие** (`SSL_ERROR_SYSCALL`). Пин не просто бесполезен — он перехватывает CloudCode у рабочего маршрута. Характерная деталь: проба по SNI `generativelanguage` на том же IP проходит, а по обоим `cloudcode-pa` — нет, поэтому «прокси живой» и «CloudCode недоступен» оказались правдой одновременно.
- **Локальный split-tunnel прокси, MITM-CA и `LD_PRELOAD` DNS-shim**. Обслуживали два предыдущих пункта. Заодно ушла зависимость `cryptography` и принудительный `GODEBUG=http2client=0` (HTTP/1.1-даунгрейд требовался только SNI-прокси).
- **Машинные патчи `.text`** переведены в opt-in (`--include-optional`). Они байт-точные под конкретную сборку: на `agy 1.2.7` `ineligibility_from_result_gate` всё ещё совпадает, а его парный `eligibility_error_gate` — уже нет. Переписывать относительный переход, смещение которого взято из другой сборки, в 224-МБ Go-бинарнике — риск попасть в середину инструкции. Строкового переименования достаточно, поэтому по умолчанию машинный код не трогается.

### Opt-in паттерны

| Паттерн | Зачем |
| :--- | :--- |
| `eligibility_error_gate`, `ineligibility_from_result_gate` | Машинный код; только для проверенной end-to-end сборки |
| `proxy_var_isolation` | Переименовывает `https_proxy` → `AG_LS_PROXY`, чтобы `agy` читал прокси из приватной переменной. **Ломаёт** работу у тех, кто маршрутизирует `agy` через собственный `https_proxy`, поэтому выключено |

---

## Миграция с версий ≤1.4.x

Прежние версии меняли системные настройки, которые теперь не нужны и могут мешать. После обновления выполните:

```bash
# Linux / macOS
./antigravity_unlock_linux.sh --cleanup-legacy     # или --cleanup-legacy на macOS

# Windows
.\antigravity_unlock_windows.ps1 -CleanupLegacy

# Пины в /etc/hosts требуют root:
sudo antigravity-unlock setup remove
```

Что удаляется:

- `/etc/systemd/resolved.conf.d/antigravity-unlock.conf` (Linux, Smart DNS drop-in);
- системный DNS, прописанный через `networksetup` (macOS) или `Set-DnsClientServerAddress` (Windows) — сбрасывается к DHCP, и только если там действительно стоят `111.88.96.50/51`;
- пины CloudCode в `/etc/hosts`, **включая немаркированные** строки, которые писали совсем старые версии и которые прежний `unpin()` не видел.

Конфиг мигрирует автоматически при любом запуске: если `strategy=pin` указывает на версию **старше** установленной, стратегия переключается на `in_place` (иначе следующий тик Guardian откатил бы рабочий `agy`). Осознанный pin на более новую версию не трогается; если версию не удалось распознать — тоже.

---

## Откат изменений (Восстановление)

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

Либо напрямую:
```bash
antigravity-unlock restore
```

Восстановление идёт из `~/.local/share/antigravity-unlocker/agy.original.bak` (Windows: `%LOCALAPPDATA%\antigravity-unlocker\`).

---

## Решение проблем

| Симптом | Причина | Действие |
| :--- | :--- | :--- |
| `Eligibility check failed` | Патч затёрт автообновлением `agy` | `antigravity-unlock patch`, затем `autostart install` |
| `Primary signature not found ... not recognised` | Незнакомая сборка: Google изменил литерал | Обновите инструмент; бинарник намеренно не тронут |
| Работало, потом перестало после обновления | Guardian не установлен | `antigravity-unlock autostart install` |
| TLS-ошибки к CloudCode | Мёртвый пин в `/etc/hosts` от ≤1.4.x | `sudo antigravity-unlock setup remove` |
| Неясно, что именно сломано | — | `antigravity-unlock doctor` |

Логи: `~/.local/share/antigravity-unlocker/unlocker.log`.

> [!NOTE]
> Вы можете создать обращение в разделе [GitHub Issues](https://github.com/NakishN/antigravity-cli-unlocker/issues).
> Также можете вступить в телеграм группу, где буду ещё многое публиковать https://t.me/NakishN

Прикладывайте к обращению вывод `antigravity-unlock doctor --json`.

---

## Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
