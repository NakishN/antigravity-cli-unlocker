# Antigravity CLI Unlocker

Патч и обход региональных ограничений для **Google Antigravity CLI (`agy`)**, **Antigravity IDE** и **Antigravity 2.0** на Linux, macOS и Windows.

Патч снимает клиентскую проверку региона. Google дополнительно проверяет IP и из РФ отвечает Gemini ошибкой `User location is not supported`. Поэтому для Gemini нужен выход: `dnspin` (без VPN), VPN или свой прокси. Claude и GPT-OSS работают из РФ напрямую.

---

## Установка

### Linux / macOS

```bash
git clone https://github.com/NakishN/antigravity-cli-unlocker.git
cd antigravity-cli-unlocker

# Linux
chmod +x antigravity_unlock_linux.sh
./antigravity_unlock_linux.sh

# macOS
chmod +x antigravity_unlock_macos.sh
./antigravity_unlock_macos.sh
```

### Windows

Запустите `antigravity_unlock_windows.bat` от имени администратора. Либо в PowerShell от администратора:

```powershell
Set-ExecutionPolicy Unrestricted -Scope Process -Force
.\antigravity_unlock_windows.ps1
```

### Готовые бинарники

[GitHub Releases](https://github.com/NakishN/antigravity-cli-unlocker/releases/latest): `.AppImage` (Linux), `.exe` (Windows), standalone (macOS).

---

## Быстрый старт

```bash
antigravity-unlock patch
antigravity-unlock doctor
antigravity-unlock autostart install
```

`patch` ставит патч, `doctor` проверяет все слои и делает живой вызов `agy`, `autostart install` защищает патч от автообновлений.

---

## Gemini без VPN: `dnspin`

Публичные unblock-DNS (geohide.ru, comss.one, dns-ai.ru) отдают адреса своих релеев для трёх хостов Google API. `dnspin` проверяет релеи живым TLS-запросом и гоняет через них только эти хосты. VPN, VPS и root не нужны; TLS остаётся end-to-end.

```bash
# Проверить и сделать один реальный вызов Gemini
antigravity-unlock dnspin test --model gemini-3.8-flash-low

# Включить для обёртки run
antigravity-unlock dnspin enable

# Запустить agy через пин
antigravity-unlock run -- -p "..." --model gemini-3.8-flash-low
```

### Чтобы работал голый `agy` (TUI, `agy -p`, IDE)

Один раз закрепить релеи в `/etc/hosts` (нужен sudo):

```bash
sudo antigravity-unlock dnspin pin-hosts
```

Если `sudo` не видит команду (она в `~/.local/bin`), укажите полный путь:

```bash
sudo ~/.local/bin/antigravity-unlock dnspin pin-hosts
```

После этого запускать `agy` как обычно. Откат:

```bash
sudo antigravity-unlock dnspin unpin-hosts
```

Если релеи сменятся или умрут:

```bash
antigravity-unlock dnspin status
sudo antigravity-unlock dnspin pin-hosts
```

Релеи — третья сторона: TLS не терминируется, OAuth-токен им не виден, но адреса могут меняться. Если `dnspin` не находит рабочий релей — используйте `model ru`, VPN или свой VPS (ниже).

---

## Если Gemini не нужен: `model ru`

Переключает `agy` на Claude/GPT-OSS. Меняется только ключ `model` в `~/.gemini/antigravity-cli/settings.json`, оригинал сохраняется в бэкап, результат проверяется живым вызовом.

```bash
antigravity-unlock model ru
antigravity-unlock model restore
```

После этого голый `agy` работает из РФ без VPN. Возможен `429 RESOURCE_EXHAUSTED` — это квота, не гео-отказ.

---

## Свой VPS или прокси: `egress`

Если нужен гарантированный выход, а не публичные релеи.

### VPS за 5 минут (Ubuntu/Debian)

На VPS:

```bash
curl -fsSLO https://raw.githubusercontent.com/NakishN/antigravity-cli-unlocker/main/scripts/setup_proxy_vps.sh
sudo bash setup_proxy_vps.sh
```

Скрипт поставит `microsocks`, включит SOCKS5-аутентификацию, проверит выход и напечатает команды. На локальной машине:

```bash
antigravity-unlock egress add 'socks5h://agy:ПАРОЛЬ@IP:1080' --label vps
antigravity-unlock egress test --model gemini-3.8-flash-low
antigravity-unlock egress enable
```

Порт нужно открыть также в firewall облака (Oracle VCN, AWS security group и т.п.).

### Любой готовый прокси

```bash
antigravity-unlock egress add socks5h://host:1080
antigravity-unlock egress add https://user:pass@host:8443 --label paid
antigravity-unlock egress test
antigravity-unlock egress enable
```

### Чтобы ходил голый `agy`

```bash
antigravity-unlock patch --only proxy_var_isolation
antigravity-unlock egress hook install
exec $SHELL
```

После самообновления `agy` этот opt-in патч может слететь — `doctor` покажет, и команду нужно повторить. Либо используйте `antigravity-unlock run`.

---

## Команды

| Команда | Что делает |
| :--- | :--- |
| `antigravity-unlock status` | состояние патча, guardian, dnspin |
| `antigravity-unlock doctor` | полная диагностика + живой вызов `agy` |
| `antigravity-unlock patch` | поставить патч |
| `antigravity-unlock dnspin test` | проверить Gemini через публичные релеи |
| `antigravity-unlock dnspin enable` | использовать `dnspin` в `run` |
| `antigravity-unlock dnspin pin-hosts` | закрепить релеи для голого `agy` (sudo) |
| `antigravity-unlock model ru` | переключить `agy` на Claude/GPT-OSS |
| `antigravity-unlock egress add/test/enable` | свой прокси или VPS |
| `antigravity-unlock autostart install` | Guardian в автозапуск |
| `antigravity-unlock restore` | вернуть оригинальный `agy` |
| `antigravity-unlock unpatch` | снять патч без бэкапа |

---

## Откат

```bash
antigravity-unlock restore              # вернуть оригинальный agy
sudo antigravity-unlock dnspin unpin-hosts   # убрать DNS-pin
antigravity-unlock model restore        # вернуть модель по умолчанию
antigravity-unlock autostart remove     # убрать Guardian из автозапуска
```

---

## Если что-то не работает

| Симптом | Что делать |
| :--- | :--- |
| `Eligibility check failed` | `antigravity-unlock patch`, затем `autostart install` |
| `User location is not supported` | `antigravity-unlock dnspin test`; для голого `agy` — `sudo antigravity-unlock dnspin pin-hosts`; либо `model ru` |
| `dnspin` не находит релей | Повторить позже, `model ru`, VPN или свой VPS |
| `TLS`/proxy ошибки | `antigravity-unlock dnspin status` или `egress test` |
| Guardian не работает | `antigravity-unlock doctor`, затем `autostart install` |
| Неясно, что сломано | `antigravity-unlock doctor` |

Логи: `~/.local/share/antigravity-unlocker/unlocker.log`.

---

## Сборка

```bash
pip install -e .
python -m pytest

python packaging/build_binaries.py
bash packaging/build_appimage.sh      # Linux
```

---

## Поддержка

[GitHub Issues](https://github.com/NakishN/antigravity-cli-unlocker/issues) · [Telegram](https://t.me/NakishN)

Лицензия: [MIT](LICENSE).
