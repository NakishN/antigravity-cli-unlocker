# Antigravity CLI Unlocker

Antigravity CLI Unlocker — инструментарий для снятия региональных ограничений в **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на Linux, macOS и Windows: версионно-независимый патч бинарника, Gemini без VPN через `dnspin`, маршрутизация через зарубежный выход (`egress`), послойная диагностика (`doctor`) и фоновый Guardian, который перепатчивает `agy` после каждого автообновления.

> **Ограничений два, а не одно.** Патч бинарника снимает клиентский eligibility-гейт. Но Google **дополнительно** проверяет IP-адрес источника на сервере и отвечает `FAILED_PRECONDITION (400): User location is not supported for the API use` — этого текста в бинарнике нет, поэтому никакой патч его не уберет. Замерено 2026-09-27 на `agy 1.2.11`/`1.2.12`: один и тот же пропатченный бинарник и один аккаунт — прямой российский выход даёт 400 на каждый запрос, тот же бинарник через SOCKS5-выход в Амстердаме отвечает на запросы модели.
>
> **Но вторая проверка навешана не на все модели.** С того же российского IP одиннадцать Gemini-моделей дают `400 User location`, а `claude-sonnet-4-6`, `claude-opus-4-6-thinking` и `gpt-oss-120b-medium` отвечают. Поэтому:
>
> - **Gemini без VPN** — `dnspin`: публичные unblock-DNS релеи, без root и без VPS. Замер 2026-10-27 из РФ: `DNSPIN_OK`.
> - **Gemini не обязателен** — `model ru`: Claude/GPT-OSS, вообще без выхода.
> - **Гарантированный выход** — `egress`/свой VPS/VPN.
>
> Подробности — в разделах [«Gemini без VPN»](#gemini-без-vpn-dns-pin-dnspin), [«Что работает без всякого выхода»](#что-работает-без-всякого-выхода-не-gemini-модели) и [«Маршрутизация через зарубежный выход»](#маршрутизация-через-зарубежный-выход-egress).

---

## Описание проекта

`agy` показывает `Eligibility check failed: Your current account is not eligible for Antigravity, because it is not currently available in your location.` Эта проверка **клиентская**: сервер возвращает protobuf-поле `ineligible`, а клиент блокирует работу, если оно заполнено. Сам текст ошибки в бинарнике отсутствует — он приходит с сервера.

За ней стоит **вторая** проверка, уже серверная: Google смотрит на IP-адрес, с которого пришёл запрос, и из неподдерживаемой страны отвечает `FAILED_PRECONDITION (400): User location is not supported for the API use`. Её не обойти патчем — только сменой адреса выхода. До 2026-09-20 российский выход работал и без этого; теперь нет.

Инструмент решает задачу шестью механизмами:

1. **Патч eligibility-гейта**. В бинарнике переименовывается строковый литерал `ineligible` → `inexigible` **той же длины**. Замена регистрозависимая и применяется ко всем вхождениям, поэтому:
   - сериализованный protobuf-дескриптор и Go struct-теги (`name=ineligible`, `json=ineligibleTiers`) переименовываются **согласованно**;
   - Go-идентификаторы (`IneligibleTier`, `IneligibleInfo`) **не затрагиваются** — бинарник продолжает линковаться;
   - серверный ключ `"ineligible"` в JSON больше не матчится ни на одно поле, гейт видит незаполненное поле и пропускает запрос;
   - длина всех замен одинакова, поэтому offsets, релокации и layout ELF/PE не меняются, а откат — побайтовый.

   Патч версионно-независим: он ищет литерал, а не машинный код и не смещения. Проверено на `agy 1.2.7` и `1.4.8` (9 вхождений, размер файла сохранён байт-в-байт).

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

5. **Маршрутизация через зарубежный выход (`egress`)** — снимает вторую, серверную проверку. `agy` нативно понимает `https_proxy`/`HTTPS_PROXY` и схемы `socks5://`/`socks5h://` (проверено замером, не предполагалось), но не имеет ни флага `--proxy`, ни ключа в `~/.gemini/config/config.json` — значит единственный рычаг это окружение процесса. Слой `egress` держит список маршрутов, измеряет их **настоящим запросом к модели** и подставляет выигравший только процессу `agy`: `git`, `curl` и пакетные менеджеры продолжают ходить напрямую. Подробности — в разделе [«Маршрутизация через зарубежный выход»](#маршрутизация-через-зарубежный-выход-egress).

6. **Gemini без VPN (`dnspin`)** — публичные «анблок-DNS» (geohide.ru, comss.one, dns-ai.ru) отдают адреса своих релеев для трёх хостов Google API; локальный CONNECT-прокси подменяет только их, не терминируя TLS. `accounts.google.com`, аватары и телеметрия идут напрямую. `/etc/hosts` и системный DNS не трогаются; для голого `agy` есть опциональный `sudo dnspin pin-hosts`. Замер 2026-10-27 из РФ: `DNSPIN_OK`, без VPN, VPS и root. Подробности — в разделе [«Gemini без VPN»](#gemini-без-vpn-dns-pin-dnspin).

---

## Основные возможности

| Параметр | Значение |
| :--- | :--- |
| **Поддерживаемые ОС** | Ubuntu 24.04+, Debian, Arch Linux, Fedora, macOS, Windows 10, Windows 11 |
| **Поддерживаемые компоненты** | Antigravity CLI (`agy`), Antigravity IDE, Antigravity 2.0 |
| **Проверено на** | `agy 1.4.8` (Linux x86_64) — патч + `dnspin` + реальный ответ Gemini без VPN; `1.2.11` — `egress` + ответы модели. Ранее: `1.2.7`, `1.1.9`–`1.1.27` |
| **Совместимость** | Версионно-независимая: ищется строковый литерал, а не машинный код |
| **Стратегии работы** | `in_place` (по умолчанию), `auto` (in-place + опциональный откат), `pin` |
| **Выход из заблокированного региона** | `dnspin` — Gemini без VPN через публичные unblock-DNS релеи (geohide/comss/dns-ai), без root; `egress` — любой `socks5`/`socks5h`/`http`/`https`, пресет `warp`, выбор по живому запросу к модели |
| **Диагностика** | `doctor` — слои бинарника, конфига, hosts, dnspin, egress, endpoint, модели и живая проверка `agy -p` в конце |
| **Автозапуск Guardian** | `systemd user unit` (Linux), `Task Scheduler` (Windows), `launchd` (macOS) |
| **Зависимости Python** | Отсутствуют (опционально `watchdog` для file-watch). SOCKS5-клиент написан вручную, а не через PySocks |
| **Права root** | Не требуются для патча/dnspin/egress; `dnspin pin-hosts` для голого `agy` — sudo один раз |
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

**Если нужен именно Gemini без VPN** — в проекте есть режим `dnspin`. Он спрашивает публичные unblock-DNS (geohide.ru, comss.one, dns-ai.ru), получает адреса их релеев, проверяет каждый живым TLS-запросом и направляет через них только три хоста Google API. VPN, VPS и root не нужны; TLS остаётся end-to-end, релей не видит OAuth-токен. Замер 2026-10-27 из РФ: `DNSPIN_OK`, без VPN и без прокси.

```bash
antigravity-unlock dnspin test --model gemini-3.8-flash-low
antigravity-unlock dnspin enable
antigravity-unlock run -- -p "..." --model gemini-3.8-flash-low

# Чтобы работал и голый `agy` (TUI), закрепи релеи в /etc/hosts — sudo один раз:
sudo /полный/путь/antigravity-unlock dnspin pin-hosts
```

Если `dnspin` не находит живой релей (публичные сервисы иногда лежат) или нужен гарантированный выход — используйте VPS/прокси ниже.

**Если Gemini не обязателен** — самый дешёвый путь сменить модель по умолчанию одной командой: гео-проверка навешана на семейство Gemini, а `claude-*` и `gpt-oss-*` с того же российского IP отвечают нормально (замер 2026-10-27 — в разделе [«Что работает без всякого выхода»](#что-работает-без-всякого-выхода-не-gemini-модели)):

```bash
# Меняет только ключ "model" в ~/.gemini/antigravity-cli/settings.json,
# сохраняет оригинал в .antigravity-unlock.bak и проверяет живым вызовом agy.
antigravity-unlock model ru

# Откатить: вернуть settings.json из бэкапа
antigravity-unlock model restore
```

После этого **голый `agy`** (и TUI, и `agy -p`) стартует на Claude и работает из РФ без VPN. Если нужен гарантированный зарубежный выход помимо `dnspin`, тогда нужен шаг 4 — VPS или прокси. **Cloudflare WARP для этого замерен и не подошёл** (выходит на российский край Cloudflare), но последовательность команд оставлена как рабочий пример настройки SOCKS5-маршрута:

```bash
# 4a. Cloudflare WARP в proxy-режиме (root нужен только на запуск службы)
sudo systemctl enable --now warp-svc
warp-cli registration show              # если пусто: warp-cli registration new
warp-cli mode proxy
warp-cli proxy port 40000
warp-cli connect

# 4b. Добавить маршрут, измерить его настоящим запросом и выбрать
antigravity-unlock egress add warp
antigravity-unlock egress test

# 4c. Чтобы голый `agy` (а не только `antigravity-unlock run`) ходил через выход
antigravity-unlock patch --only proxy_var_isolation
antigravity-unlock egress hook install
exec $SHELL
```

Вместо WARP в 4a подставьте любой прокси с реальным зарубежным выходом: `egress add socks5h://host:1080` или `egress add https://user:pass@host:8443`.

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
| `guardian` | Запущен ли Guardian, установлен ли автозапуск **и способен ли юнит вообще стартовать** |
| `hosts pin` | Не остались ли в `/etc/hosts` пины от версий ≤1.4.x |
| `egress` | Публичный IP и страна выхода |
| `endpoint` | Достаёт ли запрос до настоящего CloudCode и **почему** он отказал |
| `functional` | Реальный запуск `agy -p` — единственный слой, который не догадывается |

Проверки только читают состояние и ограничены по времени; `functional` тратит один запрос к модели, поэтому отключается через `--no-functional`.

### Слой `guardian` ловит не только «не запущен», но и «не может запуститься»

Юнит, который падает при старте, снаружи выглядит как работающая установка: файл на месте, патч применён, процесса нет. Поэтому слой `guardian` спрашивает у systemd напрямую и различает три состояния, которые снаружи неотличимы — `FAIL`, если юмит установлен, но падает или ушёл в `auto-restart`, `WARN`, если он установлен и просто сейчас не запущен, и `WARN`, если автозапуска нет вовсе.

Развилка `FAIL` и `WARN` сделана по замеру 2026-10-07: юнит с `ExecStart=/usr/bin/python3 -m antigravity_unlock guardian` был установлен, но пакет не был импортируем (`No module named antigravity_unlock`), при `Restart=always` он перезапускался каждые 15 с и только что переписал журнал; `doctor` в это время сообщал «guardian не установлен» и предлагал установить уже установленное. `autostart install` после 1.6.0 дополнительно проверяет `is-active` **после** `enable --now`, потому что `systemctl enable --now` возвращает код 0 даже тогда, когда юит не стартовал (замерено на этой же машине).

### Разрыв соединения ≠ снятый гейт

`agy` пишет **любую** неудачную попытку проверки под заголовком `Eligibility check failed`, включая оборванное TLS-соединение. Дословный вывод с этой машины:

```
error: Eligibility check failed: failed to get profile picture: Get "https://lh3.googleusercontent.com/a/ACg8ocIh...=s96-c": EOF
```

До 1.6.0 такой вывод диагностировался как «бинарник не пропатчен» и давал `FAIL` с советом перепатчить — хотя следующий же запуск проходил нормально. Теперь маркеры транспорта (`EOF`, `connection reset by peer`, `i/o timeout`, `no such host`, `http2: server sent goaway`, …) проверяются **раньше** маркеров гейта, а `functional` в таком случае выдаёт `WARN`: один оборванный запрос ничего не доказывает ни в одну сторону, совет — просто перезапустить `doctor`. Настоящий региональный отказ (`400 User location is not supported`) при этом по-прежнему распознаётся и имеет приоритет.

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

## Маршрутизация через зарубежный выход (`egress`)

Патч бинарника снимает **клиентский** eligibility-гейт. Серверную проверку IP-адреса он снять не может: текст `User location is not supported for the API use` приходит в теле ответа, и в бинарнике его нет — переименовывать нечего. Единственный способ пройти вторую проверку — чтобы соединение приходило к Google из поддерживаемой страны.

Замер 2026-09-27, `agy 1.2.11`, один пропатченный бинарник и один аккаунт, менялся только выход:

| Выход | Результат |
| :--- | :--- |
| `95.26.85.26` (RU), напрямую | `FAILED_PRECONDITION (code 400): User location is not supported for the API use.` |
| `77.105.128.240` (NL, Амстердам), SOCKS5 | модель ответила на запрос |

До 2026-09-20 российский выход работал и без маршрутизации; теперь серверная проверка включена.

### Как это устроено

`agy` не имеет ни флага `--proxy`, ни ключа прокси в `~/.gemini/config/config.json` — проверено. Зато он нативно читает `https_proxy`/`HTTPS_PROXY` и понимает `socks5://` и `socks5h://` (тоже проверено: мёртвый прокси дал `proxyconnect tcp: ... connection refused`, а оба варианта SOCKS5 дали ответ модели). Значит единственный рычаг — окружение процесса, и `egress` подставляет его **только процессу `agy`**. Никакого локального слушателя, никакого перехвата TLS, никаких подмен в DNS и `/etc/hosts`: `agy` сам обращается к настоящему адресу Google.

Выбор маршрута делается **по настоящему запросу к модели**, а не по скорости и не по доступности порта. Это принципиально: на собственном сетевом слое 1.4.x было замерено, что открытый порт и даже успешно завершённое TLS-рукопожатие полностью совместимы с тем, что CloudCode всё равно недоступен. Дешёвые сигналы используются только чтобы не тратить запрос к модели на заведомо мёртвый маршрут.

### Команды

```bash
antigravity-unlock egress status          # маршруты, выбранный, включена ли маршрутизация
antigravity-unlock egress presets         # именованные маршруты (не нужно помнить адрес)
antigravity-unlock egress add warp        # добавить пресет
antigravity-unlock egress add socks5h://host:1080
antigravity-unlock egress add https://user:pass@host:8443 --label paid
antigravity-unlock egress remove paid
antigravity-unlock egress select paid     # выбрать без измерения
antigravity-unlock egress test            # измерить все и выбрать рабочий
antigravity-unlock egress enable          # включить маршрутизацию
antigravity-unlock egress disable         # выключить (маршруты сохраняются)
antigravity-unlock egress hook install    # чтобы голый `agy` тоже ходил через выход
antigravity-unlock egress hook status
antigravity-unlock egress hook remove
```

`egress test` тратит по одному настоящему запросу к модели на каждый маршрут, дошедший до проверки портом. Первый маршрут, через который модель ответила, выбирается и сохраняется; маршруты с отказом по региону отбраковываются и повторно не пробуются. Таймаут — это **не** отказ по региону: медленный ответ не должен навсегда вычёркивать рабочий выход.

### Cloudflare WARP: проверено и **не сработало** из России

WARP в proxy-режиме поднимает локальный SOCKS5-слушатель — без TUN, без изменения системных маршрутов и без подмены DNS (в отличие от Clash/mihomo, который перехватывает DNS и ломает диагностику). Это выглядело как идеальный выход без своего сервера, поэтому замер сделан честно, а не по документации.

**Результат замера 2026-09-27 (российский провайдер, AS8402 Vimpelcom): не работает.** WARP выходит на ближайший край Cloudflare, а он всё ещё в России — `104.28.232.201`, `AS13335 Cloudflare`, гео-локация Самара. Google ответил тем же `FAILED_PRECONDITION (400)`, и `egress test` честно показал `REGION-BLOCKED`. Бесплатный WARP-туннель — **не** гарантированный выход из заблокированной страны: Cloudflare маршрутизирует к ближайшей точке, а не к зарубежной.

Сами команды при этом рабочие (пригодятся, если точка подключения изменится или появится WARP+). Обратите внимание: подкоманда регистрации — `registration new`, а **не** `register`; root нужен только на запуск службы, сокет `/var/run/cloudflare-warp/warp_service` имеет права `0777`, поэтому сам `warp-cli` работает без sudo.

```bash
sudo systemctl enable --now warp-svc      # root нужен только на запуск службы
warp-cli registration show                # если пусто: warp-cli registration new
warp-cli mode proxy                       # "Establish a tunnel for use in a SOCKS5 proxy"
warp-cli proxy port 40000                 # слушает на 127.0.0.1:40000
warp-cli connect

# ОБЯЗАТЕЛЬНО проверить страну выхода до того, как на что-то рассчитывать
curl -s --max-time 15 --proxy socks5h://127.0.0.1:40000 https://ipinfo.io/json
antigravity-unlock egress add warp
antigravity-unlock egress test            # измеряет настоящим запросом к модели
```

Откат: `warp-cli disconnect && warp-cli mode warp`, службу выключает `sudo systemctl disable --now warp-svc`.

Именно для этого `egress test` измеряет, а не предполагает, а `doctor` отдельным слоем ловит случай «прокси поднялся, но выходит всё равно в заблокированной стране»: `[FAIL] exit warp - reachable, but it exits in RU, which is blocked`.

### Что работает без всякого выхода: не-Gemini модели

Замер 2026-10-27, реальный российский выход `95.26.84.28` (AS8402 Vimpelcom, Казань), прямой маршрут без VPN, TUN и прокси, пропатченный `agy 1.4.8`, менялась только модель:

| Модель | Ответ |
| :--- | :--- |
| `gemini-3.8-flash-low` | `FAILED_PRECONDITION (400): User location is not supported` |
| `claude-sonnet-4-6` | `RU_CLAUDE_OK` — реальный ответ модели |
| `gpt-oss-120b-medium` | `RU_GPTOSS_OK` — реальный ответ модели |

Из 14 моделей в `agy models` одиннадцать — Gemini, и гео-проверка навешана именно на них. **В TUI по умолчанию стоит Gemini**, поэтому 400 приходит раз за разом независимо от качества патча. Переключение на не-Gemini модель снимает проблему без прокси, VPS и root.

`agy` хранит модель по умолчанию в `~/.gemini/antigravity-cli/settings.json`, в ключе `model`, причём **display-name**, а не id (`"Claude Sonnet 4.6 (Thinking)"`, не `claude-sonnet-4-6`). Это проверено правкой ровно одного значения: до правки `agy -p` без `--model` отвечал 400, после — `DEFAULT_CLAUDE_OK`. Команда `model ru` делает это штатно:

```bash
antigravity-unlock model status          # какая модель стартует и есть ли бэкап
antigravity-unlock model ru              # claude-sonnet-4-6 + живая проверка
antigravity-unlock model ru --model claude-opus-4-6-thinking
antigravity-unlock model set gpt-oss-120b-medium
antigravity-unlock model restore         # вернуть settings.json из бэкапа
```

Инструмент меняет **только** ключ `model`, остальной файл (включая большой список разрешений, которым владеет `agy`) сохраняется по возможности побайтово. Оригинал кладётся в `settings.json.antigravity-unlock.bak` один раз и повторными вызовами не перезаписывается. Изменение действует со следующего запуска `agy`; если TUI уже открыт, закройте его, чтобы он не перезаписал файл своим состоянием.

Ограничения, которые команда не отменяет: пул Claude/GPT общий и узкий, поэтому возможен `429 RESOURCE_EXHAUSTED` — это не гео-отказ. Если нужен именно Gemini, сначала попробуйте [`dnspin`](#gemini-без-vpn-dns-pin-dnspin) — он работает без VPN; если публичные релеи недоступны, остаётся [`egress`](#маршрутизация-через-зарубежный-выход-egress)/свой VPS/VPN. Патч бинарника при этом остаётся обязательным — он снимает клиентский eligibility-гейт, без него не работает ни одна модель.

Замер 2026-09-27 на выходе `95.26.84.70` давал для не-Gemini моделей только `429` и оставлял оговорку: квота могла проверяться раньше гео. Живые ответы `RU_CLAUDE_OK` и `RU_GPTOSS_OK` 2026-10-27 эту оговорку для `claude-sonnet-4-6` и `gpt-oss-120b-medium` снимают.

### Gemini без VPN: DNS-pin (`dnspin`)

Публичные «анблок-DNS» сервисы (geohide.ru, comss.one, dns-ai.ru) отвечают на запросы `daily-cloudcode-pa.googleapis.com`, `generativelanguage.googleapis.com` и `cloudcode-pa.googleapis.com` **адресами своих релеев**, а не настоящими IP Google. Релеи пробрасывают TCP до Google из поддерживаемой страны, не терминируя TLS: сертификат остаётся Google-овским, OAuth-токен внутри TLS. Это тот же механизм, что в [Asalio123/antigravity-unlocker](https://github.com/Asalio123/antigravity-unlocker) и [confeden/Antigravity](https://github.com/confeden/Antigravity), но здесь он не правит `/etc/hosts` и не требует root: локальный CONNECT-прокси подменяет адрес только для трёх хостов.

Замер 2026-10-27, российский ISP (95.26.84.28, AS8402 Vimpelcom), VPN/TUN/прокси выключены, `agy 1.4.8` пропатчен:

```text
daily-cloudcode-pa.googleapis.com -> 159.194.200.33  (geohide)
generativelanguage.googleapis.com -> 142.251.153.2   (comss)
cloudcode-pa.googleapis.com       -> 206.223.251.18  (comss)

agy -p "Say DNS_PIN_GEMINI_OK" --model gemini-3.8-flash-low
-> DNS_PIN_GEMINI_OK
```

Команды:

```bash
antigravity-unlock dnspin status     # опросить провайдеров и проверить релеи TLS-пробой
antigravity-unlock dnspin test --model gemini-3.8-flash-low
antigravity-unlock dnspin enable     # использовать пин в 'antigravity-unlock run'
antigravity-unlock dnspin disable
antigravity-unlock run -- -p "..." --model gemini-3.8-flash-low
```

Для голого `agy` есть два пути. Самый простой — закрепить релеи в `/etc/hosts` (sudo один раз):

```bash
sudo /полный/путь/antigravity-unlock dnspin pin-hosts
# откат:
sudo /полный/путь/antigravity-unlock dnspin unpin-hosts
```

Тогда `agy` (и TUI, и `agy -p`, и IDE) резолвит три API-хоста в релеи без обёртки и без переменных окружения. Если релеи сменились, `doctor` покажет мёртвый пин и попросит повторить `pin-hosts`.

Второй путь — без root: поднять пин отдельным процессом и указать его в окружении:

```bash
antigravity-unlock dnspin serve --port 18999
# в другом терминале:
HTTPS_PROXY=http://127.0.0.1:18999 agy -p "..." --model gemini-3.8-flash-low
```

Ограничения: релеи принадлежат третьей стороне, их адреса меняются, сервисы могут умереть; `dnspin status` и `doctor` проверяют их живым TLS-запросом, а при неудаче нужно вернуться на `model ru`, VPS или VPN. Провайдеры отдают подмену только клиентам из блокируемого региона; вне РФ они вернут настоящие адреса Google, и `dnspin` просто не найдёт кандидатов.

### Свой выход за 5 минут: любой Ubuntu/Debian VPS (SOCKS5)

В проекте **нет и не будет собственного общего прокси, который мы бы хостили**. Такой прокси видел бы OAuth-трафик всех пользователей, был бы единственной точкой отказа и его бы быстро начали абьюзить. Поэтому проект даёт механизм, а выход пользователь держит свой: публичные релеи `dnspin` — отдельный, явно помеченный режим, не наш сервис. Самый предсказуемый вариант — свой VPS (Oracle Cloud Always Free, Hetzner, любой другой) + `microsocks`:

1. Создайте Ubuntu 24.04 VM в поддерживаемой стране: Frankfurt, Amsterdam, Helsinki, Ashburn.
2. Откройте TCP-порт (по умолчанию `1080`) в firewall облака: Oracle VCN security list, AWS security group, Hetzner firewall. Скрипт правит только `ufw`/`firewalld` внутри VM и не имеет доступа к панели облака.
3. На VPS:

```bash
curl -fsSLO https://raw.githubusercontent.com/NakishN/antigravity-cli-unlocker/main/scripts/setup_proxy_vps.sh
sudo bash setup_proxy_vps.sh
```

Скрипт поставит `microsocks`, создаст отдельного системного пользователя, включит SOCKS5-аутентификацию, сгенерирует случайный пароль, проверит выход и напечатает готовую команду. Креды сохраняются в `/root/antigravity-egress.txt` с правами `600`. Посмотреть конфиг без изменений: `bash setup_proxy_vps.sh --dry-run`.

4. На **локальной** машине:

```bash
antigravity-unlock egress add 'socks5h://agy:ПАРОЛЬ@IP:1080' --label vps
antigravity-unlock egress test --model gemini-3.8-flash-low
antigravity-unlock egress enable
```

5. Чтобы ходил голый `agy`, а не только `antigravity-unlock run`:

```bash
antigravity-unlock patch --only proxy_var_isolation
antigravity-unlock egress hook install
exec $SHELL
```

**Почему SOCKS5, а не HTTP-прокси с Basic Auth.** Замерено 2026-10-27: `agy` полностью работает через SOCKS5 с логином/паролем (и список моделей, и вызов модели), но через HTTP Basic-auth прокси падает на получении списка моделей — `timed out waiting for available models`. Поэтому скрипт ставит `microsocks`, а не `tinyproxy`. Схема в команде — `socks5h://`, чтобы имя резолвил прокси, а не локальный DNS (иначе Clash/mihomo fake-ip отдаст `198.18.x.x`).

**Oracle Cloud Always Free:** создайте инстанс Ubuntu 24.04 в Frankfurt или Amsterdam (подойдёт и ARM Ampere, и AMD micro), добавьте в VCN security list ingress-правило TCP `1080` с вашего IP, зайдите по SSH и запустите скрипт. На ARM те же пакеты `microsocks`/`curl` ставятся из apt. Бесплатный тариф Oracle требует карту только для верификации; списаний на Always Free ресурсах нет.

Ограничения, которые скрипт не отменяет: SOCKS5-пароль идёт по сети в открытом виде (RFC 1929), но трафик до Google остаётся TLS. Поэтому ставьте сильный пароль и по возможности ограничьте круг адресов через `--allow 203.0.113.7/32`. Публичный прокси без ограничений легко абьюзят. Скрипт рассчитан на Ubuntu/Debian; локальная часть (`egress`) работает на Linux, macOS и Windows.

### Бесплатные варианты: что проверено

| Вариант | Gemini | VPN / VPS / root | Результат |
| :--- | :--- | :--- | :--- |
| **`dnspin`** (geohide / comss / dns-ai) | **да** | нет / нет / нет | замер 2026-10-27: `DNSPIN_OK`; зависит от третьих лиц |
| `model ru` (Claude / GPT-OSS) | нет | нет / нет / нет | работает, но без Gemini |
| свой VPS + `microsocks` | да | нет / **да** / да | предсказуемо, но нужен VPS |
| любой доверенный VPN | да | **да** / нет / нет | самый простой гарантированный вариант |
| публичные SOCKS/HTTP | ? | нет | нестабильны, видят метаданные; не рекомендуется |
| Tor | нет | нет | Google отвечает `403` (проверено 2026-10-27) |
| Cloudflare WARP без Zero Trust | нет | нет | выходит на российском крае Cloudflare (Самара) |
| Psiphon | нет | нет | замер 2026-10-27: SOCKS поднялся, но ни один туннель не установился |
| общий прокси проекта | да | — | один аккаунт на всех, трафик и абьюз; не делаем |

Отсюда архитектура: **Gemini без VPN — `dnspin`; без Gemini — `model ru`; гарантированный выход — свой VPS/VPN**. `dnspin` — это не прокси проекта, а клиент к публичным unblock-DNS: он получает адреса релеев, проверяет их TLS-сертификат и гоняет через них только `daily-cloudcode-pa`, `generativelanguage` и `cloudcode-pa`. Остальной трафик, включая `accounts.google.com`, идёт напрямую. Релеи — третья сторона: они видят метаданные, но не OAuth-токен (TLS не терминируется), могут меняться и умирать (xbox-dns.ru умер в октябре 2026). Поэтому `dnspin status`/`doctor` проверяют их живым запросом, а `model ru` остаётся запасным путём.

Механизм найден в открытом порту [Asalio123/antigravity-unlocker](https://github.com/Asalio123/antigravity-unlocker) и оригинальном [confeden/Antigravity](https://github.com/confeden/Antigravity); здесь он реализован без `/etc/hosts` и без root — локальным CONNECT-прокси.

### Любые другие прокси

Поддерживаются схемы `socks5`, `socks5h`, `http`, `https`, в том числе с логином и паролем в URL. Пароль никогда не печатается: в `status`, в отчёте `test` и в сообщениях об ошибках он заменяется на `***`.

**`socks5h` предпочтительнее `socks5`.** Разница в том, кто резолвит имя цели: `socks5` — сам `agy` (локально), `socks5h` — прокси (на своей стороне). Если в системе работает Clash/mihomo в режиме fake-ip, локальный DNS на любой A-запрос отвечает синтетическим адресом из `198.18.0.0/16`; с `socks5` этот подставной адрес уйдёт прокси, и соединение не состоится. С `socks5h` имя резолвится за туннелем, где DNS честный. Пресет `warp` поэтому задан как `socks5h://`.

### Чтобы работал голый `agy`, а не только обёртка

`antigravity-unlock run` подставляет окружение сам. Но обычно `agy` запускают напрямую, и обёртка, которую никто не вызывает, ничего не лечит. Для этого есть `egress hook`: он пишет в стартовый файл оболочки помеченный блок с `export AG_LS_PROXY=...`.

`AG_LS_PROXY` — приватная переменная, которую `agy` начинает читать только после паттерна `proxy_var_isolation` (переименовывает литерал `https_proxy` той же длины):

```bash
antigravity-unlock patch --only proxy_var_isolation
antigravity-unlock egress hook install
exec $SHELL                                  # или открыть новый терминал
```

Здесь именно `--only`, а не `--include-optional`. Флаг `--include-optional` включает **весь** opt-in ярус целиком, а в нём смешаны два разных вида правок: строковые переименования той же длины (безопасны на любой сборке) и байт-точные перезаписи машинного кода, смещения для которых сняты с одной конкретной сборки. На `agy 1.2.11` `--include-optional` дополнительно переписал бы `ineligibility_from_result_gate` — 16 байт машинного кода. `agy` обновляется сам, поэтому применять такое вслепую нельзя; `--only proxy_var_isolation` применяет ровно одно строковое переименование. Неизвестное имя в `--only` отклоняется со списком допустимых (exit 2), а не молча применяет ноль паттернов.

Именно поэтому `hook install` **отказывается** работать без этого паттерна: единственная переменная, которую читает не пропатченный `agy`, — это `https_proxy`, а экспортировать её из профиля оболочки значит завернуть в туннель ещё и `git`, `curl` и пакетные менеджеры.

Два свойства блока обязательны и проверены тестами:

- он заключён между маркерами `# >>> antigravity-unlocker egress >>>` и `# <<< ... <<<`, а `hook remove` удаляет ровно то, что между ними — соседние строки профиля не затрагиваются. Немаркированные записи в `/etc/hosts` от версий ≤1.4.x до сих пор приходится вычищать отдельной командой, потому что прежний `unpin()` их не находил;
- повторная установка обновляет существующий блок, а не добавляет второй.

**Грабля:** переименовывается только литерал в нижнем регистре, поэтому `agy` по-прежнему читает `HTTPS_PROXY` в верхнем регистре, и Go смотрит его первым. Если он у вас экспортирован, он перекроет `AG_LS_PROXY`. `egress hook status` это показывает.

---

## Как это работает на самом деле

Раздел написан потому, что прежние версии документировали механизм, который не работал.

**Клиентский eligibility-гейт обходит только патч бинарника.** Проверено 2026-09-20 на `agy 1.2.7`: после переименования 9 вхождений `ineligible` CLI отвечает на реальные запросы (`agy -p` → осмысленный ответ, `agy models` → полный список моделей), с российского IP-адреса выхода, без VPN, прокси и подмены DNS.

**Это утверждение перестало быть полным 2026-09-27.** Тот же пропатченный бинарник и тот же аккаунт с российского выхода теперь получают `FAILED_PRECONDITION (400): User location is not supported for the API use` на каждый запрос, а через SOCKS5-выход в Амстердаме отвечают нормально. Значит включилась вторая, серверная проверка — по IP-адресу источника. Патч по-прежнему необходим (без него не проходит первая проверка), но **уже не достаточен**: из заблокированного региона нужен выход — `egress`, `dnspin` или VPN. Подробные замеры — в разделах [«Gemini без VPN»](#gemini-без-vpn-dns-pin-dnspin) и [«Маршрутизация через зарубежный выход»](#маршрутизация-через-зарубежный-выход-egress).

Что при этом оказалось бесполезным и удалено в 1.5.0:

- **Smart DNS (`xbox-dns.ru`, `comss.one`, `geohide.ru`)**. В 1.5.0 удалён: замер 2026-09-20 показывал, что для `cloudcode-pa` и `daily-cloudcode-pa` эти резолверы отдают те же IP, что `8.8.8.8`, а подменялся только `generativelanguage`. 2026-10-27 картина изменилась: geohide/comss начали отдавать рабочие релеи для `daily`/`cloudcode`. В 1.6.0 это вернулось **узко** — как `dnspin`, без правки системного DNS и только для трёх хостов; старый системный Smart DNS остаётся удалённым.
- **SNI-прокси и пины в `/etc/hosts`**. Конкретный старый IP (`45.155.204.190`, Москва, Cloud.ru) принимает TCP на 443, но **не завершает TLS-рукопожатие** (`SSL_ERROR_SYSCALL`), поэтому пин на него был бесполезен и перехватывал CloudCode у рабочего маршрута. `dnspin` проверяет TLS-сертификат каждого кандидата и отбрасывает такие адреса; его релеи рукопожатие проходят.
- **Локальный split-tunnel прокси, MITM-CA и `LD_PRELOAD` DNS-shim**. Обслуживали два предыдущих пункта. Заодно ушла зависимость `cryptography` и принудительный `GODEBUG=http2client=0` (HTTP/1.1-даунгрейд требовался только SNI-прокси).
- **Машинные патчи `.text`** переведены в opt-in (`--include-optional`). Они байт-точные под конкретную сборку: на `agy 1.2.7` `ineligibility_from_result_gate` всё ещё совпадает, а его парный `eligibility_error_gate` — уже нет. Переписывать относительный переход, смещение которого взято из другой сборки, в 224-МБ Go-бинарнике — риск попасть в середину инструкции. Строкового переименования достаточно, поэтому по умолчанию машинный код не трогается.

### Opt-in паттерны

| Паттерн | Зачем |
| :--- | :--- |
| `eligibility_error_gate`, `ineligibility_from_result_gate` | Машинный код; только для проверенной end-to-end сборки |
| `proxy_var_isolation` | Переименовывает `https_proxy` → `AG_LS_PROXY`, чтобы `agy` читал прокси из приватной переменной. Обязателен для `egress hook install` — только так можно прописать выход в профиле оболочки, не завернув в туннель `git` и `curl`. По-прежнему **ломает** работу тем, кто маршрутизирует `agy` через собственный `https_proxy`, поэтому по умолчанию выключен |

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

### DNS-pin (`dnspin`)

Если использовали `dnspin pin-hosts`, уберите блок из `/etc/hosts` отдельно — `restore` его не трогает:

```bash
sudo antigravity-unlock dnspin unpin-hosts
```

---

## Решение проблем

| Симптом | Причина | Действие |
| :--- | :--- | :--- |
| `Eligibility check failed` | Патч затёрт автообновлением `agy` | `antigravity-unlock patch`, затем `autostart install` |
| `... failed to get profile picture ...: EOF` | Оборванное соединение, а не гейт: `agy` пишет под этим заголовком любую сетевую ошибку | Ничего не чинить, просто перезапустить `doctor` |
| `[FAIL] guardian ... fails to start` | Юит установлен, но падает при старте (обычно `No module named antigravity_unlock`) | `antigravity-unlock autostart remove && antigravity-unlock autostart install`, затем `journalctl --user -u antigravity-unlocker-guardian.service -n 30` |
| `Start request repeated too quickly` | Исчерпан `StartLimitBurst` после серии падений | `systemctl --user reset-failed antigravity-unlocker-guardian.service` (с 1.6.0 делается автоматически при установке) |
| `Primary signature not found ... not recognised` | Незнакомая сборка: Google изменил литерал | Обновите инструмент; бинарник намеренно не тронут |
| Работало, потом перестало после обновления | Guardian не установлен | `antigravity-unlock autostart install` |
| `User location is not supported` в Gemini | Прямой RU-выход; `dnspin` выключен или не используется | `antigravity-unlock dnspin test --model gemini-3.8-flash-low`; для голого `agy` — `sudo antigravity-unlock dnspin pin-hosts` |
| `dnspin` не находит релей | Публичные unblock-DNS лежат или не подменяют для вашего региона | Повторить позже; `antigravity-unlock model ru` или свой VPS/VPN |
| TLS-ошибки к CloudCode | Мёртвый пин в `/etc/hosts`: старый от ≤1.4.x или устаревший `dnspin` | Старый — `sudo antigravity-unlock setup remove`; `dnspin` — `sudo antigravity-unlock dnspin pin-hosts` |
| Неясно, что именно сломано | — | `antigravity-unlock doctor` |

Логи: `~/.local/share/antigravity-unlocker/unlocker.log`.

> [!IMPORTANT]
> `autostart install` создаёт постоянное окружение в `~/.local/share/antigravity-unlocker/runtime` и пишет в юит именно его интерпретатор, а не тот, из которого запущена команда. Это сделано намеренно: пакет часто живёт как обычный checkout, и интерпретатор, который импортирует его из домашнего каталога в интерактивной оболочке, **не** импортирует его при `cwd=$HOME` — то есть ровно так, как его запускает systemd.

> [!NOTE]
> Вы можете создать обращение в разделе [GitHub Issues](https://github.com/NakishN/antigravity-cli-unlocker/issues).
> Также можете вступить в телеграм группу, где буду ещё многое публиковать https://t.me/NakishN

Прикладывайте к обращению вывод `antigravity-unlock doctor --json`.

---

## Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
