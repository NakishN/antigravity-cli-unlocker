# Changelog

All notable changes to the Antigravity CLI Unlocker project will be documented in this file.

## [1.5.0] - 2026-09-20

Релиз сделан после того, как установка перестала работать на `agy 1.2.7`, и последующей проверки каждого механизма замерами. Главный вывод: **eligibility-гейт снимает только патч бинарника**, а весь сетевой слой (Smart DNS, SNI-прокси, локальный прокси, DNS-shim) не работал и удалён.

### Added
- **Версионно-независимый primary-паттерн `protobuf_ineligible_bare`**: переименовывает каждое вхождение голого литерала `ineligible` → `inexigible`, а не только Go struct-тег `name=ineligible`. На `agy 1.2.7` это 9 вхождений вместо 2: дополнительно переписывается сериализованный protobuf-дескриптор, поэтому дескриптор и struct-теги остаются согласованными. Замена регистрозависимая, так что Go-идентификаторы `IneligibleTier` / `IneligibleInfo` не затрагиваются и бинарник продолжает линковаться.
- **Команда `doctor`**: послойная диагностика (бинарник → стратегия → guardian → `/etc/hosts` → egress → CloudCode → живой запуск `agy -p`). Каждый слой выдаёт вердикт и готовую команду починки. Флаги `--no-network`, `--no-functional`, `--json`.
- **Трёхstate-классификация бинарника** (`classify_binary`): `patched` / `unpatched` / `foreign`. `foreign` означает, что нет ни сигнатуры, ни её замены — сборка незнакомая, и бинарник **не трогается**, чтобы `agy` показал собственную ошибку.
- **`repatch_if_needed`** с явными исходами (`patched`, `already`, `foreign`, `failed`) — guardian больше не путает «обновление затёрло патч» с «мы не знаем эту сборку».
- **Однопроходный потоковый подсчёт сигнатур** (`count_needles_stream`): все паттерны считаются за один проход по файлу чанками по 8 МиБ вместо чтения ~220 МБ в память на каждый опрос. Замер полного ценза `agy 1.2.7` — 1.1 с.
- **Опция `include_optional`** (флаг `patch --include-optional` или ключ конфига) для opt-in паттернов.
- **Модуль `hosts_cleanup.py`**: удаление пинов из `/etc/hosts`, включая немаркированные строки от совсем старых версий. Только удаление — создать пин модуль не может.
- **Миграция конфига** (`migrate_config`): дописывает новые ключи и снимает `strategy=pin`, если закреплённая версия **старше** установленной.
- **Тесты**: `test_config.py`, `test_doctor.py`, `test_guardian.py`, `test_hosts_cleanup.py`; существенно расширен `test_patcher.py` (состояния классификации, исходы repatch, сохранение размера, opt-in паттерны, потоковый подсчёт на нескольких размерах чанка). Итого 81 тест + 16 subtests.

### Changed
- **Стратегия по умолчанию: `auto` → `in_place`.** `agy` обновляется сам, поэтому стратегия, патчащая установленную версию, переживает обновление, а `pin` борется с апдейтером бесконечно.
- **Машинные патчи `.text` переведены в opt-in.** На `agy 1.2.7` `ineligibility_from_result_gate` ещё совпадает, а парный `eligibility_error_gate` — уже нет: переписывать относительный переход со смещением из другой сборки в 224-МБ Go-бинарнике означает рисковать попаданием в середину инструкции. Строкового переименования достаточно.
- **`proxy_var_isolation`** (`https_proxy` → `AG_LS_PROXY`, 11 байт в 11 байт) добавлен как opt-in и по умолчанию выключен: он заставляет `agy` игнорировать ambient-прокси пользователя. `HTTPS_PROXY` намеренно не трогается.
- **`run` больше не поднимает прокси**: патч при необходимости и `os.execv` в `agy`. На POSIX процесс-обёртка исчезает, поэтому сигналы, изменения размера терминала и controlling TTY достаются `agy` напрямую — существенно для полноэкранного TUI.
- **`endpoint apply` больше не вызывается автоматически** из `patch`. Обоснование («`daily-` хост подменяется unblock-DNS, а production — нет») исчезло вместе со Smart DNS, а оба хоста проверены и возвращают одинаковый `401 CREDENTIALS_MISSING`. Молча править пользовательский `settings.json` без измеримой пользы не нужно.
- **Убрана зависимость `cryptography`** (её использовал только удалённый `ca_manager`) и `--collect-all cryptography` из PyInstaller-сборки. Рантайм-зависимостей у пакета теперь нет.
- **Скрипты установки больше не требуют root/администратора** и не меняют системный DNS. В Windows `.bat` убран принудительный UAC-запрос, который к тому же терял аргументы: при перезапуске через `Start-Process '%~f0' -Verb RunAs` параметры не передавались, и `-DryRun`/`-Restore` молча игнорировались.
- **Guardian** переразрешает путь к `agy` на каждом тике (автообновление может перенести бинарник) и логирует смену `size`/`mtime` как событие самообновления.
- **`status`** дополнительно печатает состояние патча и включённость opt-in паттернов.

### Fixed
- **`agy 1.2.7` не патчился.** Автообновление `agy` затёрло патч, а активная стратегия `pin` на `1.1.27` не соответствовала установленной версии. После переименования всех 9 вхождений `agy -p` возвращает реальные ответы модели, `agy models` — полный список; размер файла сохранён байт-в-байт (224268544).
- **Тихий даунгрейд в режиме `auto`.** При неудаче патча `enforce_strategy` откатывал бинарник на закреплённую версию, подменяя «эту сборку мы пока не умеем патчить» на «у вас сломан `agy`». Теперь откат возможен только при `allow_pin_fallback=true`.
- **`patch_binary` сообщал «already patched» для незнакомой сборки**, потому что ветка «нечего применять» не различала «патч на месте» и «сигнатуры нет вовсе».
- **`_is_patched_binary` читал весь файл в память** на каждый опрос Guardian (~220 МБ каждые 30 с). Переведён на потоковую классификацию.
- **Мёртвый пин в `/etc/hosts` не обнаруживался.** `45.155.204.190` (Москва, Cloud.ru) принимает TCP на 443, но не завершает TLS-рукопожатие. Записи к тому же были **без маркеров**, поэтому прежний `unpin()` их не видел и не удалял.
- **Проба SNI-прокси давала ложный «живой» результат**: проверялся только первый домен из списка, а SNI-прокси отвечает по-SNI. На одном IP `generativelanguage` проходил TLSv1.3, а оба `cloudcode-pa` — нет.
- **`doctor` больше не делает ложных выводов.** `401 CREDENTIALS_MISSING` доказывает только достижимость, а не принятие региона: Google проверяет креды раньше географии, поэтому неаутентифицированная проба до гео-отказа просто не доходит. Область egress из `BLOCKED_COUNTRIES` даёт `warn`, а не `fail` — решает слой `functional`. Область `endpoint` опрашивает **настоящий** Google через DoH, а не путь `/etc/hosts`.
- **Ложное срабатывание Guardian**: он логировал «self-update reverted the patch» из-за `mtime` от собственной записи патча. Отпечаток теперь снимается до проверки, а сохраняется после.
- **Потеря совпадений на EOF** в потоковом подсчёте при файле короче окна переноса — закрыто регрессионным тестом.

### Removed
- `hosts_manager.py` — пины `/etc/hosts` к SNI-прокси (заменён на removal-only `hosts_cleanup.py`).
- `proxy.py` — split-tunnel прокси и мульти-провайдерный Smart DNS (`xbox-dns.ru`, `comss.one`, `geohide.ru`).
- `ca_manager.py` — генерация и установка MITM-CA в системное доверенное хранилище.
- `dns_shim.c`, `shim_builder.py` — `LD_PRELOAD`-перехват `getaddrinfo()`.
- Команды `proxy` и `install-ca`; команда `setup` оставлена только для очистки (`apply` объясняет отказ).
- Шаги настройки системного DNS из всех трёх скриптов установки (`systemd-resolved` drop-in на Linux, `networksetup -setdnsservers` на macOS, `Set-DnsClientServerAddress` на Windows). Замер `dig` показал, что эти резолверы возвращают для `cloudcode-pa.googleapis.com` и `daily-cloudcode-pa.googleapis.com` те же реальные IP Google, что и `8.8.8.8` — подмены нет.
- `scripts/test_hosts_pin.sh`.
- Принудительный `GODEBUG=http2client=0` в `runner` (HTTP/1.1-даунгрейд требовался только SNI-прокси).

## [1.4.1] - 2026-09-05

### Added
- Поддержка `agy 1.1.27`: запись в `versions.json` с перечнем применяемых wildcard-паттернов и SHA-256 исходного и пропатченного бинарников.
- Тест `test_1_1_22_and_1_1_27_supported` — проверяет, что для обеих версий зарегистрированы машинные патчи гейтов.

### Changed
- Версия пакета `1.4.0` → `1.4.1`; в README добавлены `1.1.27` в списки поддерживаемых версий.

## [1.4.0] - 2026-08-28

### Added
- **SNI proxy bypass (ключевое)**: Новый механизм обхода серверной проверки `FAILED_PRECONDITION: User location is not supported`. Домены `daily-cloudcode-pa.googleapis.com`, `cloudcode-pa.googleapis.com` и `generativelanguage.googleapis.com` пиннятся к geohide.ru SNI-прокси (`45.155.204.190`) через `/etc/hosts`. Прокси принимает TLS с оригинальным SNI и пересылает запрос на реальный сервер Google, обходя IP-геоблокировку.
- **DNS shim (LD_PRELOAD)**: Альтернативный механизм без root-прав. C-библиотека `dns_shim.c` перехватывает `getaddrinfo()` и подменяет DNS-ответы для целевых доменов. Компилируется автоматически при первом запуске.
- **Команда `setup`**: `sudo antigravity-unlock setup apply` — добавляет SNI proxy записи в `/etc/hosts`. `setup remove` — удаляет. `setup status` — проверяет статус.
- **`GODEBUG=http2client=0`**: Автоматически устанавливается в runner для принудительного HTTP/1.1 (SNI-прокси не поддерживает HTTP/2 ALPN).
- **Модуль `hosts_manager.py`**: Управление записями `/etc/hosts` с маркерами для безопасного добавления/удаления.
- **Модуль `shim_builder.py`**: Автоматическая компиляция `dns_shim.so` из C-исходника.
- **Fallback SNI proxy IPs в proxy.py**: Когда Smart DNS провайдеры не подменяют домен, прокси использует известные рабочие SNI proxy IP.

### Fixed
- **Обход бага agy v1.1.21+**: Модельные вызовы (`streamGenerateContent`) обходят `HTTPS_PROXY` — решено через hosts pinning + DNS shim.
- **HTTP/2 hang**: SNI-прокси не поддерживает ALPN — решено через `GODEBUG=http2client=0`.

## [1.3.0] - 2026-08-28

### Added
- **Поддержка agy v1.1.22**: Протестировано и подтверждено на `agy 1.1.22`. Все 9 wildcard-патчей (включая машинный код `eligibility_error_gate` и `ineligibility_from_result_gate` для linux_x86_64) применяются корректно. Модель отвечает успешно через `streamGenerateContent`.
- **Мульти-провайдерный Smart DNS**: Заменён одиночный DNS-провайдер на систему из трёх провайдеров (`xbox-dns.ru`, `comss.one`, `geohide.ru`) с автоматической гонкой и валидацией по эталонным резолверам (`8.8.8.8`, `1.1.1.1`). Первый провайдер, вернувший подменённый IP (отличный от эталонного), выигрывает. Добавлена защита от ISP DPI-стабов.
- **IDE Endpoint Override**: Добавлен модуль `endpoint.py` для переопределения `jetski.cloudCodeUrl` в настройках Antigravity IDE на `daily-cloudcode-pa.googleapis.com`.
- **IPv4 Priority**: Добавлен модуль `ipv4_priority.py` для установки приоритета IPv4 над IPv6 через `/etc/gai.conf`.
- **Расширенное обнаружение бинарников**: Улучшен `discovery.py` — добавлен поиск `agy` в директориях расширений Antigravity IDE.

### Changed
- **Прокси-модуль**: Полностью переработан `proxy.py` — мульти-провайдерный DNS с кэшированием провайдера, TTL 300с, логирование выбора провайдера.
- **versions.json**: Обновлены wildcard-паттерны, добавлена платформа-специфичная фильтрация для машинного кода.

### Fixed
- **Тесты прокси**: Переписаны `test_proxy.py` для новой мульти-провайдерной архитектуры.
- **Тесты пиннера**: Исправлены моки в `test_pinner.py` для корректной изоляции.

## [1.2.2] - 2026-08-23

### Added
- **Verified v1.1.19 Support**: Registered `1.1.19` in `versions.json`. Its machine-code eligibility gates (`backend.(*AuthStatus).EligibilityError`, `backend.IneligibilityFromResult`) remain byte-identical to `1.1.17`/`1.1.18`, so the existing size-preserving wildcard code patches apply unchanged (`eligibility_error_gate` 1x, `ineligibility_from_result_gate` 1x). Confirmed by disassembly of the `.text` gate sites and end-to-end: the patched binary returns a model response to `agy -p` instead of `Eligibility check failed: ... not currently available in your location`. Recorded verified original/patched SHA-256 hashes and updated the README supported-version matrix.
- **Version-registry test**: Added `tests/test_versions.py` asserting the `1.1.19` entry exists and references both machine-code gate patterns, and that every version's `wildcard_patterns` resolve to defined top-level patterns.

### Notes
- No new patch logic was required: `agy` had auto-updated to `1.1.19`, replacing the patched binary with a fresh unpatched one. Re-running the unlocker (`strategy=in_place`/`auto`) re-applies the patch. Install the Guardian autostart service (`--autostart`) to re-patch automatically after future auto-updates.

## [1.2.1] - 2026-08-22

### Added
- **Verified v1.1.18 Support**: Registered `1.1.18` in `versions.json`. Its machine-code eligibility gates (`backend.(*AuthStatus).EligibilityError`, `backend.IneligibilityFromResult`) are byte-identical to `1.1.17`, so the existing size-preserving wildcard code patches apply unchanged (each matches exactly once). Recorded verified original/patched SHA-256 hashes for the release. Updated README supported-version matrix.

### Fixed
- **Test Isolation Leaking Into Live Config**: `tests/test_pinner.py` mocked only `pinner.get_app_dir`, but `config.py`/`logging_utils.py` hold their own `get_app_dir` bindings, so `save_config()` wrote the real `~/.local/share/antigravity-unlocker/config.json` during test runs. A 58-byte dummy pin fixture leaked in as `strategy=pin, pinned_size=58`, which made the guardian roll freshly installed releases back to `1.1.9`. Added an autouse `conftest.py` fixture that redirects every `get_app_dir` binding to a temp directory so tests can no longer mutate real user state.

## [1.2.0] - 2026-08-21

### Added
- **Multi-Strategy Patch System**: Added user-selectable patch strategies (`auto`, `in_place`, `pin`):
  - `auto` (Default): Attempts in-place machine code patching on the installed version; gracefully falls back to pinned `1.1.9` if an unsupported version is encountered.
  - `in_place`: Directly patches the installed `agy` binary without rollback or downgrade.
  - `pin`: Strictly enforces rolling back to and locking the verified `1.1.9` release.
- **Machine Code Eligibility Patch for v1.1.17+**: Added x86_64 machine code `.text` byte patches for `backend.(*AuthStatus).EligibilityError` and `backend.IneligibilityFromResult` to completely bypass Go runtime eligibility checks in newer stripped binaries.
- **CLI Strategy Options**: Added `--strategy {auto,in_place,pin}` flag to CLI commands and `pin strategy` subcommand to save default preference.

### Fixed
- **Pinner Configuration**: Resolved size and checksum mismatches in `config.json` during binary pinning cycles.

## [1.1.0] - 2026-08-17

### Added
- **Version Pinning System**: Added `agy` binary version pinning with automatic rollback protection.
- **Guardian Daemon**: Background monitor to enforce pinned versions and prevent automatic client overwrites.
- **Autostart Service**: Cross-platform service management (systemd, Windows Task Scheduler, macOS launchd).
- **Atomic File Replacement**: Safe binary substitution on Linux preventing `ETXTBSY` (Text file busy) errors.

## [1.0.1] - 2026-08-06

### Fixed
- **Smart DNS Resolution in SplitTunnelProxy**: Integrated a pure-Python UDP DNS A-record resolver with in-memory TTL caching. Target Google API endpoints are resolved via Smart DNS queries instead of using the DNS server IP as a TCP target, eliminating TLS certificate verification errors (`*.xbox-dns.ru`).
- **Direct Auth Routing**: Removed `~accounts.google.com` from `systemd-resolved` domain rules in `antigravity_unlock_linux.sh` to preserve direct authentication.

## [3.0.0] - 2026-08-05

### Added
- **Split-Tunnel Local Micro-Proxy**: Built-in async HTTP/SOCKS5 proxy server. Bypasses geoblocks for `generativelanguage.googleapis.com` while maintaining `DIRECT` unproxied connections for authentication domains (`accounts.google.com`, `oauth2.googleapis.com`).
- **Run-Wrapped CLI Mode**: Execute `antigravity-unlock run -- agy <args>` without root/administrator privileges or system-wide DNS changes.
- **Modular Python Architecture**: Refactored monolithic script into a clean `antigravity_unlock` Python package with `discovery`, `patcher`, `proxy`, `runner`, and `cli` modules.
- **Registry & Wildcard Byte Patcher**: Added `versions.json` registry with exact SHA-256 offsets and wildcard pattern matching fallback.
- **Standalone Binary & AppImage Builds**: Added PyInstaller script (`packaging/build_binaries.py`) and Linux AppImage packager (`packaging/build_appimage.sh`).
- **GitHub Release Automation**: Workflow (`.github/workflows/release.yml`) for automatic matrix builds of AppImage, Windows `.exe`, and standalone executables.
- **Automated Unit Testing Suite**: Added unittest suite (`tests/test_patcher.py`, `tests/test_proxy.py`).

## [2.2.0] - 2026-08-03

### Added
- **Modular Core**: Refactored core Python patcher (`antigravity_unlock.py`) with `--dry-run`, `--force`, and `--restore` capabilities.
- **SHA-256 Verification**: Automatic SHA-256 calculation and verification before and after binary patching.
- **Logging**: Integrated persistent file logging to `~/.local/share/antigravity-unlocker/unlocker.log`.
- **Windows Default Route Detection**: Enhanced PowerShell script to detect default interface via `Get-NetRoute -DestinationPrefix "0.0.0.0/0"`.
- **macOS Compatibility**: Added candidate paths for macOS Antigravity CLI installations.
- **CI/CD Integration**: Added GitHub Actions workflow (`.github/workflows/ci.yml`) for automated linting and ShellCheck validation.
- **Strict Documentation**: Clean technical documentation without emojis.

## [2.1.0] - 2026-08-03

### Added
- Initial cross-platform release for Linux (Ubuntu 24.04 / Debian / Arch) and Windows (10 / 11).
- Support for `systemd-resolved` DNS configuration.
- Machine code gate patching for x64 and ARM64 architectures.
