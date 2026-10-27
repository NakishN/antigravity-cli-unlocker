# Changelog

All notable changes to the Antigravity CLI Unlocker project will be documented in this file.

## [1.6.1] - 2026-10-27

Патч-релиз: исправлена обработка оборванного SOCKS5-рукопожатия на Windows, ложное предупреждение `doctor` на intentional `dnspin` hosts-пин, релизная сборка больше не подхватывает старые tracked-файлы из `dist/`, README сокращён до инструкций.

### Fixed
- `egress._recv_exact` оборачивает `ConnectionAbortedError` (WinError 10053) в `EgressError` — на Windows тест и реальный SOCKS5-клиент больше не падают сырым исключением.
- `doctor` распознаёт `dnspin`-блок в `/etc/hosts` как намеренный и не советует `setup remove` (раньше это могло сломать рабочий hosts-пин).
- Release-workflow загружает только собранные per-OS артефакты и проверяет `--version`; старые `dist/`/`build/` удалены из git и добавлены в `.gitignore`.
- README переписан в практическую инструкцию: установка, `dnspin`, `model ru`, VPS/egress, команды, откат, проблемы, сборка.
- Тесты: 274 passed + 16 subtests на Linux, Windows и macOS.

## [1.6.0] - 2026-10-07

Релиз собран вокруг слоя `egress` (региональные проверки две, а не одна) и вокруг четырёх настоящих поломок, найденных на живой машине 2026-10-07 после того, как `agy` был пропатчен вручную и выглядел исправным.

Главный вывод второй части: **установка выглядела здоровой ровно тогда, когда guardian был мёртв**. Юнит был на месте, патч в бинарнике есть, `agy` отвечает — а `systemctl enable --now` в это время возвращал код 0 при юните, который не стартовал, и `doctor` писал «guardian не установлен», предлагая установить уже установленное. Ниже ровно то, что оказалось сломано, с замерами.

---

### Первая часть релиза: региональные проверки (замеры 2026-09-27)

Релиз начат с того, что пропатченный `agy 1.2.11`/`1.2.12` начал отвечать `FAILED_PRECONDITION (code 400): User location is not supported for the API use` на каждый запрос с российского выхода. Главный вывод: **региональных проверок две, а не одна**, и патч бинарника снимает только первую.

Замер 2026-09-27, один и тот же пропатченный бинарник и один аккаунт, менялся только выход:

| Выход | Результат |
| :--- | :--- |
| `95.26.85.26` (RU), напрямую | `FAILED_PRECONDITION (code 400): User location is not supported for the API use.` |
| `77.105.128.240` (NL, Амстердам), SOCKS5 | `PONG` — модель ответила |

Текста ошибки в бинарнике нет (0 вхождений; `FAILED_PRECONDITION` встречается 9 раз как код состояния), он приходит в теле ответа с сервера. Значит вторая проверка идёт по IP-адресу источника, и **никакой байт-патч её не снимает** — нужен выход в поддерживаемой стране. Утверждение из 1.5.0 «с российского IP-адреса выхода, без VPN, прокси и подмены DNS» было верным на 2026-09-20 и перестало быть верным; README исправлен.

Два дополнительных замера того же дня, оба меняют рекомендацию:

- **Гео-гейт навешан на семейство Gemini, а не на все модели.** Прямой российский выход `95.26.84.70`, один пропатченный бинарник, менялась только модель: `gemini-3.8-flash-high` → `400 User location`, а `claude-sonnet-4-6`, `claude-opus-4-6-thinking` и `gpt-oss-120b-medium` → `429 RESOURCE_EXHAUSTED`, то есть до гео-отказа не доходит. Из 14 моделей в `agy models` одиннадцать — Gemini, и в TUI по умолчанию стоит именно Gemini. Независимое подтверждение: в интерактивном сеансе после `/model` → Claude Opus тот же запрос дал `Individual quota reached`, а не отказ по локации. **Незакрытая оговорка:** `429` доказывает, что запрос дошёл до системы квот, но не доказывает однозначно отсутствие гео-проверки — если квота оценивается раньше гео, после сброса лимита возможен тот же `400`. Живой ответ не-Gemini модели с российского IP в рамках замера получить не удалось (квота исчерпана на ~3 часа).
- **Cloudflare WARP из России не помогает.** Поднят в proxy-режиме, слушатель на `127.0.0.1:40000` работал, но выход оказался на российском краю Cloudflare: `104.28.232.201`, `AS13335 Cloudflare`, гео-локация Самара. `egress test` честно вернул `REGION-BLOCKED`. Бесплатный WARP маршрутизирует к ближайшей точке, а не к зарубежной, поэтому как «выход без своего сервера» он не годится. Заодно исправлена команда регистрации: `warp-cli registration new`, а не `register` (такой подкоманды нет); root нужен только на `systemctl` — сокет `/var/run/cloudflare-warp/warp_service` имеет права `0777`, поэтому `warp-cli` работает непривилегированно.

### Added
- **Слой `egress`** (`egress.py`): список маршрутов в конфиге, выбор рабочего по **настоящему запросу к модели**, подстановка окружения только процессу `agy`. Схемы `socks5`, `socks5h`, `http`, `https`, логин/пароль в URL. Пресет `warp` (Cloudflare WARP в proxy-режиме, `socks5h://127.0.0.1:40000`) оставлен как удобно настраиваемый локальный SOCKS5, но в его `hint` записан результат замера: из России он выходит на российский край Cloudflare и гейт не снимает.
- **SOCKS5-клиент на stdlib** (RFC 1928 CONNECT + RFC 1929 user/pass). Зависимости по-прежнему нулевые: PySocks не добавлялся. Цель всегда передаётся доменным именем (ATYP 0x03), то есть резолвит прокси — это поведение `socks5h`, и оно переживает локальный DNS, который врёт (Clash/mihomo fake-ip `198.18.0.0/16`).
- **Команды `egress`**: `status`, `presets`, `add`, `remove`, `select`, `test`, `enable`, `disable`, `hook install|remove|status`.
- **`egress hook`** — помеченный блок `export AG_LS_PROXY=...` в стартовом файле оболочки, чтобы через выход ходил **голый `agy`**, а не только `antigravity-unlock run`. `remove` удаляет ровно то, что между маркерами; повторная установка обновляет блок, а не добавляет второй.
- **Флаг `patch --only PATTERN`** (повторяемый) и `list_pattern_names()`. `--include-optional` включает весь opt-in ярус целиком, а в нём смешаны строковые переименования той же длины (безопасны на любой сборке) и байт-точные перезаписи машинного кода, снятые с одной конкретной сборки. На `agy 1.2.12` `--include-optional` дополнительно переписал бы `ineligibility_from_result_gate` (16 байт машинного кода). Неизвестное имя в `--only` отклоняется со списком допустимых и exit 2, а не молча применяет ноль паттернов.
- **Слой `exit` в `doctor`**: доступность каждого маршрута и страна выхода выбранного. Отдельно ловит случай «прокси поднялся, но выходит всё равно в заблокированной стране».
- **60 тестов `test_egress.py` + 22 теста `test_shellhook.py` + 7 тестов `--only`**. Классификация agy тестируется на **дословно снятом выводе**, а не на придуманных строках; SOCKS5 — на настоящем локальном сервере и настоящей цели за ним, без моков. Итого **274 passed + 16 subtests** (в 1.5.0 было 87 + 16).
- **Постоянное окружение Guardian** (`runtime` в `get_app_dir()`, то есть `~/.local/share/antigravity-unlocker/runtime`, а не во временных каталогах — иначе оно не пережило бы перезагрузку). Создаётся через `uv venv`, если `uv` есть, иначе `python -m venv`; импортируемость обеспечивается `antigravity_unlock.pth` со путём к исходникам, а не `pip install`: пакет не имеет рантайм-зависимостей, а PEP 668 на системном Python всё равно мешает установке. Идемпотентно. В юит попадает именно этот интерпретатор, а не тот, из которого запущена команда.
- **`guardian_unit_problem()` в `autostart.py`**: одна функция отвечает на вопрос «может ли юит вообще запуститься» для **обоих** вызывающих — установки и `doctor`. Раньше ответ на этот вопрос был продублирован, и они разошлись.
- **Тесты `test_logging_utils.py`**: тесты, которые пишут в боевой лог пользователя, воспроизводятся явно — оба падают до исправления и проходят после.

### Changed
- **`doctor check_functional` теперь ходит тем же путём, что и `agy`** (`route=`). Без этого исправная установка с настроенным выходом выглядела бы сломанной: прямой путь из заблокированного региона даёт 400 независимо от качества патча.
- **`runner`** подставляет окружение выхода через `os.execve` и печатает выбранный маршрут в stderr. Окружение собирается на процесс, системные переменные не трогаются — `git`, `curl` и пакетные менеджеры идут напрямую. Перед подстановкой все ambient-переменные прокси (`http_proxy`/`HTTPS_PROXY`/`all_proxy` и прочие) удаляются: Go смотрит регистр верхним первым, и оставленное чужое значение молча перекрыло бы наш маршрут.
- `BLOCKED_COUNTRIES` и `GEO_URLS` перенесены в `egress.py` как единственный источник: диагностика и маршрутизация не должны расходиться в том, какие регионы заблокированы.
- `hook install` **отказывается** работать, пока `proxy_var_isolation` не применён или `agy` не найден. Проверка делается до записи: блок, который `agy` игнорирует, хуже ошибки — он выглядит установленным и молча не работает.
- **Юит Guardian ограничен в перезапусках**: `StartLimitIntervalSec=300` / `StartLimitBurst=5` в `[Unit]`. Раньше `Restart=always` + `RestartSec=15` давали бесконечный молчаливый цикл: за один день systemctl сделал 137 попыток, и в журнале это было единственное, что происходило.
- **`autostart install` теперь это констатирует.** Команда проверяет, импортируется ли пакет тем интерпретатором, который попадёт в юит, **запуская проверку из временного каталога**: из checkout тот же интерпретатор импортирует пакет успешно, а при `cwd=$HOME` — нет, и именно это различие порождало crash-loop.
- **`doctor`, слой `guardian`, отвечает на вопрос «работает ли он», а не «установлен ли он».** Юит, который падает при старте, снаружи неотличим от работающей установки: файл на месте, патч применён, процесса нет.
- **`endpoint.py` больше не утверждает, что выбор хоста ни на что не влияет.** Это утверждение стояло на неаутентифицированном пробнике от 2026-09-20, где оба хоста отдавали одинаковый `401 CREDENTIALS_MISSING` — при том что сам проект в 1.5.0 писал, что такой пробник не может их различить. По upstream (`#1016`, `#1155`) и собственному замеру от 2026-10-07 гейт применяется бэкендом **по хосту**: на `cloudcode-pa.googleapis.com` ошибка локации действительно исчезает, сменяясь `429`. Правка задокументирована со ссылками; автоматическое применение override не возвращено.

### Fixed
- **Регионный 400 больше не выдаётся за непропатченный бинарник.** В `GATE_MARKERS` был `failed_precondition`, и серверный отказ по IP диагностировался как «eligibility-гейт всё ещё активен» с советом перепатчить рабочий бинарник. Классификация переведена на общую `classify_agy`, где маркеры прокси проверяются **раньше** маркеров гейта: при недоступном прокси `agy` печатает `Eligibility check failed: Post "...loadCodeAssist": proxyconnect tcp: ...`, то есть текст про eligibility при причине «прокси не запущен». На этот случай есть отдельный регрессионный тест.
- `describe_route` и `parse_route` **печатали пароль**: URL по умолчанию становился меткой маршрута, а метка попадает в `status`, в отчёт `test` и в сообщения об ошибках. Маскирование теперь делается один раз на границе (`redact_url`), а не в каждом месте печати.
- `_dechunk` возвращал пустое тело, если в нём не было `\r\n` (то есть если поток на самом деле не был chunked).
- **Оборванное соединение выдавалось за снятый eligibility-гейт.** Дословный вывод с машины: `error: Eligibility check failed: failed to get profile picture: Get "https://lh3.googleusercontent.com/a/ACg8ocIh...=s96-c": EOF` — это рваное TLS-соединение за Clash TUN, а следующий запуск проходил нормально. `agy` пишет под заголовком `Eligibility check failed` **любую** неудачную попытку проверки, а `doctor` на этом выводе ставил `FAIL` с советом «перепатчить бинарник», который патчить было нечего. Добавлен статус `transient` и слой маркеров транспорта (`EOF`, `connection reset by peer`, `i/o timeout`, `no such host`, `http2: server sent goaway`, …), который проверяется **раньше** маркеров гейта; `functional` в этом случае даёт `WARN` — один оборванный запрос не доказывает ничего ни в одну сторону. Приоритет настоящего регионального 400 при этом сохранён, есть тест на оба порядка.
- **Guardian был мёртв, а установка об этом не знала.** Юит `antigravity-unlocker-guardian.service` содержал `ExecStart=/usr/bin/python3 -m antigravity_unlock guardian`, но пакет не был установлен и не импортировался: `No module named antigravity_unlock`, код выхода 1, `Restart=always` — 137 перезапусков к 13:15. Патч в это время был наложен вручную, то есть `agy` выглядел исправным, а защиты от следующего самообновления не существовало. Добавлено постоянное окружение в `~/.local/share/antigravity-unlocker/runtime`; юит теперь использует его интерпретатор.
- **`autostart install` рапортовал об успехе для мёртвого юита.** Замерено на этой машине: `systemctl --user enable --now <unit>` печатает ошибку задания и **возвращает код 0**, когда юит не стартовал, а `install` доверял именно этому коду. Плюс юит, исчерпавший `StartLimitBurst`, вообще отказывается стартовать до `reset-failed`. Теперь установка делает `reset-failed` перед `enable --now` и спрашивает `is-active` **после**; если юит не поднялся, команда возвращает ненулевой код и даёт готовую команду `journalctl`, а не рапорт об успехе.
- **`doctor` искал несуществующие файлы автозапуска.** Проверка смотрела `antigravity-unlocker.service` и `com.antigravity.unlocker.plist`, тогда как `autostart` ставит `antigravity-unlocker-guardian.service` и `com.antigravity.unlocker.guardian.plist`. Теперь пути берутся из самих функций `autostart`, поэтому проверка и установка не могут разойтись.
- **Тесты писали в боевой лог пользователя.** `get_logger()` мемоизировал логгер, и `FileHandler` привязывался к `~/.local/share/antigravity-unlocker/unlocker.log` ещё на этапе сбора тестов — до того, как автоприменяемая фикстура подменяет `get_app_dir`. В логе отслеживается до 772 строк, из которых 26 — фиктивные «Active strategy updated to: pin» с версиями `9.9.9` и путями `/tmp/tmpXXXX`. Сброса `_LOGGER` в фикстуре мало: объект логгера общий, а `get_logger` добавлял файловый обработчик только при пустом списке обработчиков. `get_logger` переписан так, чтобы решать **по пути обработчика**: устаревшие файловые обработчики удаляются и закрываются, нужный добавляется, если подходящего нет. Загрязнённый лог почищен (оригинал сохранён), проверено: прогон `pytest` больше не добавляет в него ни строки.


## Замер 2026-10-27: модель по умолчанию — это отдельный переключатель

Проверено с реального российского выхода `95.26.84.28` (AS8402 Vimpelcom, Казань), прямой маршрут, VPN/TUN/прокси выключены, `agy 1.4.8` пропатчен, менялась только модель:

| Модель | Ответ |
| :--- | :--- |
| `gemini-3.8-flash-low` | `FAILED_PRECONDITION (400): User location is not supported for the API use.` |
| `claude-sonnet-4-6` | `RU_CLAUDE_OK` — реальный ответ модели |
| `gpt-oss-120b-medium` | `RU_GPTOSS_OK` — реальный ответ модели |

Вторая половина замера объясняет, почему до этого «не работало» даже у пропатченной установки: `agy` стартует с моделью из `~/.gemini/antigravity-cli/settings.json`, ключ `model`, и там лежит **display-name** (`"Gemini 3.8 Flash (High)"`), а не id. Правка ровно одного значения на `"Claude Sonnet 4.6 (Thinking)"` превратила `agy -p` без `--model` из 400 в `DEFAULT_CLAUDE_OK`. Это и есть самый дешёвый способ работать из РФ: без VPN, VPS, root и без прокси.

### Added
- **Команда `model`**: `status`, `ru`, `set <id|name>`, `restore`. `model ru` выбирает не-Gemini модель (по умолчанию `claude-sonnet-4-6`), меняет только ключ `model`, один раз сохраняет оригинал в `settings.json.antigravity-unlock.bak` и проверяет результат живым вызовом `agy -p`. `model restore` возвращает файл из бэкапа.
- **`scripts/setup_proxy_vps.sh`**: универсальный bootstrap для любого Ubuntu/Debian VPS — ставит `microsocks`, создаёт отдельного системного пользователя, включает SOCKS5-аутентификацию, открывает `ufw`/`firewalld`, проверяет выход и печатает готовую команду `egress add`. Флаги `--dry-run`, `--port`, `--user`, `--password`, `--allow`, `--no-test`. Это и есть ответ на «как этим будут пользоваться другие»: проект не содержит чужих узлов и подписок, каждый пользователь поднимает свой выход одним скриптом. 8 тестов dry-run, включая URL-кодирование пароля и запрет shell-метасимволов в пароле.
- **Замер 2026-10-27: HTTP Basic Auth несовместим с `agy`.** Через HTTP-прокси с Basic Auth `agy models` падает в `timed out waiting for available models`, а `agy -p --model ...` — в `model ... is not recognized`; через SOCKS5 с RFC 1929 username/password и список моделей, и реальный вызов модели работают. Поэтому VPS-скрипт построен на `microsocks`, а не на `tinyproxy`; это же объясняет, почему в README схема `socks5h://`, а не `http://`.
- **Раздел README «Свой выход за 5 минут»** и таблица «почему нет встроенного бесплатного выхода»: публичные SOCKS, Tor, WARP и Psiphon проверены и отброшены как общий вариант; бесплатный путь без VPN — `model ru`, Gemini — только через собственный выход.
- **Слой `model` в `doctor`**: отдаёт `FAIL` с готовой командой, когда стартовая модель — Gemini, а выход в заблокированной стране; отдаёт `OK` для Claude/GPT-OSS с указанием замера. Раньше этот слой отсутствовал, и исправная установка выглядела сломанной.
- **27 тестов `test_model.py` + 6 тестов слоя `model`**: бэкап, восстановление, сохранение остальных ключей, повторный вызов не перезаписывает оригинал, вложенный `model` не затрагивается, офлайн-разрешение id/display-name.

### Fixed
- **`doctor` утверждал, что из заблокированного региона отклоняется «каждый вызов модели».** Замер 2026-10-27 показал: только Gemini. Формулировки слоёв `egress` и `exit` исправлены на «каждый вызов Gemini» и дополнены ссылкой на `model ru`; иначе пользователь шёл за прокси, который ему не нужен.


## Замер 2026-10-27 (2): Gemini без VPN через DNS-подмену

Главный результат: **Gemini заработал из РФ без VPN, без VPS, без root и без чужой подписки**. Механизм найден в открытом порту [Asalio123/antigravity-unlocker](https://github.com/Asalio123/antigravity-unlocker) и оригинале [confeden/Antigravity](https://github.com/confeden/Antigravity): публичные «анблок-DNS» сервисы отвечают на запросы трёх хостов Google адресами своих релеев, а не настоящими IP. Релеи пробрасывают TCP до Google из поддерживаемой страны, **не терминируя TLS**, поэтому сертификат остаётся Google-овским, а OAuth-токен — внутри TLS.

Замер на живом аккаунте, российский ISP `95.26.84.28` (AS8402 Vimpelcom), VPN/TUN/прокси выключены, `agy 1.4.8` пропатчен:

| Хост | Подменённый IP | Провайдер |
| :--- | :--- | :--- |
| `daily-cloudcode-pa.googleapis.com` | `159.194.200.33` | geohide.ru |
| `generativelanguage.googleapis.com` | `142.251.153.2` | comss.one |
| `cloudcode-pa.googleapis.com` | `206.223.251.18` | comss.one |

```
agy -p "Say DNS_PIN_GEMINI_OK" --model gemini-3.8-flash-low
-> DNS_PIN_GEMINI_OK
```

Проверено также `agy models` и повторный вызов через пин; `doctor` показывает `[ ok ] dnspin` и `agy completed a real prompt end-to-end via dnspin: 'DOCTOR_OK'`.

### Added
- **Модуль `dnspin.py`**: UDP- и DoH-запросы к geohide/comss/dns-ai, сравнение с эталонным резолвером (8.8.8.8/1.1.1.1), TLS-проба каждого кандидата с проверкой сертификата, выбор двух самых быстрых релеев на хост и локальный CONNECT-прокси, который подменяет адрес **только** для трёх хостов Google API. `/etc/hosts`, root и системный DNS не трогаются; `accounts.google.com`, аватары и телеметрия идут напрямую.
- **Команды `dnspin`**: `status`, `test --model`, `run -- <agy args>`, `serve --port/--refresh`, `enable`, `disable`. `run` автоматически поднимает пин, печатает выбранные IP и останавливает прокси после выхода agy.
- **Слой `dnspin` в `doctor`**: запускает пин, проверяет релеи и проводит финальный `agy -p` именно через него; при недоступности публичных сервисов честно говорит об этом и отдаёт `FAIL`, а не выдаёт прямой RU-выход за рабочий.
- **9 тестов `test_dnspin.py`**: разбор DNS wire-формата, исключение baseline-адресов, дедупликация кандидатов, статус без релеев и реальный CONNECT-тест локального прокси на echo-сервере.
- **`dnspin pin-hosts` / `unpin-hosts`**: закрепляют выбранные релеи в `/etc/hosts` между маркерами `# >>> antigravity-unlocker dnspin >>>`, чтобы **голый `agy`** (TUI, `agy -p`, IDE) работал без обёртки, переменных окружения и патча. Нужен sudo один раз; `doctor` проверяет, что запиненные IP живы, и просит повторить `pin-hosts`, если релей умер. `hosts_cleanup.find_pins()` научился исключать этот блок, чтобы не путать его с опасными остатками <=1.4.x.
- **6 тестов на hosts-пин**: идемпотентная замена блока, сохранение остальных строк, разбор, отсутствие ложного «legacy pin», отказ без root.
- **README**: раздел «Gemini без VPN: DNS-pin (`dnspin`)», обновлённые быстрый старт и таблица бесплатных вариантов; указаны авторы механизма.

### Caveats
- Релеи принадлежат третьей стороне: видят метаданные (но не OAuth-токен — TLS не терминируется), меняют адреса и могут умереть. `dnspin status`/`doctor` проверяют их живым TLS-запросом; при отказе остаются `model ru`, свой VPS или VPN.
- Провайдеры отдают подмену только клиентам из блокируемого региона; вне РФ `dnspin` не найдёт кандидатов и честно скажет об этом.


## Замер 2026-10-07: что работает без зарубежного выхода

Проверено на живом аккаунте с российского IP `95.26.84.46` (AS29125), глобальный VPN выключен, переменные прокси из окружения убраны:

| Модель | Результат |
| :--- | :--- |
| `gemini-3.8-flash-high` | `FAILED_PRECONDITION (code 400): User location is not supported for the API use.` |
| `claude-sonnet-4-6` | ответила |
| `claude-opus-4-6-thinking` | ответила |
| `gpt-oss-120b-medium` | ответила |
| `gemini-3.8-flash-high` + выход `EE` | ответила |

Итог: гейт (2) — серверный и по аккаунту, патчем бинарника не снимается; но он **навешан на семейство Gemini**, поэтому `claude-*` и `gpt-oss-*` работают с российского выхода вообще без всякой маршрутизации. Отдельно подтверждено, что патч работает: исходное клиентское сообщение «not eligible ... not currently available in your location» больше не появляется ни разу — вместо него приходит серверный 400.

Методологическая оговорка, стоившая одного ложного результата: переменная `HTTPS_PROXY` была унаследована от процесса, породившего сессию, и не была записана ни в одном из `~/.bashrc` / `~/.profile` / `/etc/environment`. `agy` — Go-клиент и её уважает, поэтому первый тест Gemini «прошёл», выйдя через прокси, тогда как `curl http://ifconfig.me` показывал российский IP: переменная задана только в верхнем регистре и покрывает TLS. Любой чистый замер обязан снимать `HTTPS_PROXY` / `NO_PROXY` из окружения.

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
- **Тесты**: `test_config.py`, `test_doctor.py`, `test_guardian.py`, `test_hosts_cleanup.py`; существенно расширен `test_patcher.py` (состояния классификации, исходы repatch, сохранение размера, opt-in паттерны, потоковый подсчёт на нескольких размерах чанка). Итого 87 тестов + 16 subtests (было 25 тестов).

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
