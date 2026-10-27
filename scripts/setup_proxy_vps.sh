#!/bin/bash
# ============================================================================
#  antigravity-cli-unlocker - generic VPS egress bootstrap
#
#  Поднимает на Ubuntu/Debian VPS SOCKS5-прокси с логином/паролем (microsocks),
#  чтобы им мог пользоваться ЛЮБОЙ человек со своим VPS. Никаких общих
#  аккаунтов, подписок и зашитых адресов: только машина пользователя.
#
#  Почему SOCKS5, а не HTTP-прокси с Basic Auth: замерено 2026-10-27, что
#  agy проходит через SOCKS5 с RFC 1929 auth (и список моделей, и вызов
#  модели), но через HTTP Basic-auth прокси падает на получении списка
#  моделей ("timed out waiting for available models"). Поэтому здесь
#  microsocks, а не tinyproxy.
#
#  Зачем: патч agy снимает клиентский eligibility-гейт, но Google отдельно
#  проверяет IP источника и из RU/BY/IR/CU/KP/SY/CR отвечает
#  "User location is not supported". Это лечится только выходом в
#  поддерживаемой стране. Свой VPS - самый предсказуемый такой выход:
#  трафик идёт по TLS до Google, прокси видит только шифрованный поток.
#
#  Использование (на VPS, от root):
#     sudo bash setup_proxy_vps.sh
#     sudo bash setup_proxy_vps.sh --port 1080 --user agy --allow 203.0.113.7/32
#     bash setup_proxy_vps.sh --dry-run          # только показать конфиг
#
#  После запуска скрипт печатает готовую команду для локальной машины:
#     antigravity-unlock egress add 'socks5h://agy:ПАРОЛЬ@IP:1080' --label vps
#     antigravity-unlock egress test --model gemini-3.8-flash-low
#     antigravity-unlock egress enable
#
#  ВАЖНО: порт нужно открыть ещё и в firewall облака (Oracle VCN security
#  list, AWS security group, Hetzner firewall и т.п.). Скрипт правит только
#  ufw/firewalld внутри самой VM.
# ============================================================================

set -euo pipefail

PORT=1080
PROXY_USER="agy"
PASSWORD=""
ALLOW="0.0.0.0/0"
DRY_RUN=0
RUN_TEST=1

ENV_FILE="/etc/antigravity-egress.env"
LAUNCHER="/usr/local/bin/antigravity-egress"
UNIT="/etc/systemd/system/antigravity-egress.service"
SERVICE_USER="agyproxy"

usage() {
    cat <<'EOF'
Usage: sudo bash setup_proxy_vps.sh [options]

  --port PORT       порт SOCKS5 (по умолчанию 1080)
  --user USER       логин (по умолчанию agy)
  --password PASS   пароль (по умолчанию случайные 32 hex-символа)
  --allow CIDR      какие адреса могут подключаться (по умолчанию 0.0.0.0/0)
                    для статического домашнего IP лучше --allow 203.0.113.7/32
  --dry-run         показать конфиг и команды, ничего не менять
  --no-test         не проверять прокси локальным curl
  -h, --help        эта справка

Скрипт рассчитан на Ubuntu/Debian. На VPS должен быть systemd и root.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

info() { echo "[*] $*"; }
ok()   { echo "[OK] $*"; }
warn() { echo "[!] $*"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)      PORT="${2:-}"; shift 2 ;;
        --user)      PROXY_USER="${2:-}"; shift 2 ;;
        --password)  PASSWORD="${2:-}"; shift 2 ;;
        --allow)     ALLOW="${2:-}"; shift 2 ;;
        --dry-run)   DRY_RUN=1; shift ;;
        --no-test)   RUN_TEST=0; shift ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "unknown argument: $1 (try --help)" ;;
    esac
done

[[ "$PORT" =~ ^[0-9]+$ ]] || die "port must be a number"
(( PORT >= 1024 && PORT <= 65535 )) || die "port must be between 1024 and 65535"
[[ "$PROXY_USER" =~ ^[A-Za-z0-9._-]+$ ]] || die "user may contain only letters, digits, . _ -"
[[ "$ALLOW" =~ ^[0-9A-Fa-f:.]+(/[0-9]{1,3})?$ ]] || die "allow must be an IP or CIDR"

if [[ -z "$PASSWORD" ]]; then
    if command -v openssl >/dev/null 2>&1; then
        PASSWORD="$(openssl rand -hex 16)"
    elif command -v python3 >/dev/null 2>&1; then
        PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
    else
        PASSWORD="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
    fi
fi

# The launcher sources the env file, and the URL is printed for the user.
# Keep the password to a conservative alphabet: no shell metacharacters, no
# quotes, no whitespace. Generated passwords are hex and always pass.
if ! printf '%s' "$PASSWORD" | grep -qE '^[A-Za-z0-9._~@:%^*+=-]+$'; then
    die "password may contain only letters, digits and . _ ~ @ : % ^ * + = -"
fi

urlenc() {
    python3 - "$1" <<'PY' 2>/dev/null || printf '%s' "$1"
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=""))
PY
}
URL_USER="$(urlenc "$PROXY_USER")"
URL_PASS="$(urlenc "$PASSWORD")"

detect_public_ip() {
    local ip=""
    for url in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
        ip="$(curl -4 -fsS --max-time 5 "$url" 2>/dev/null || true)"
        [[ -n "$ip" ]] && break
    done
    if [[ -z "$ip" ]]; then
        ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    fi
    printf '%s' "${ip:-<VPS_PUBLIC_IP>}"
}

# In dry-run the public IP is intentionally a placeholder: the config can be
# inspected on any machine, without network access or root.
if [[ "$DRY_RUN" -eq 1 ]]; then
    PUBLIC_IP="<VPS_PUBLIC_IP>"
else
    PUBLIC_IP="$(detect_public_ip)"
fi

render_env() {
    cat <<EOF
# antigravity-cli-unlocker egress credentials.
# This file is read by /usr/local/bin/antigravity-egress (systemd service
# antigravity-egress.service). It is chmod 640 root:${SERVICE_USER}.
PORT='${PORT}'
PROXY_USER='${PROXY_USER}'
PROXY_PASSWORD='${PASSWORD}'
EOF
}

render_launcher() {
    cat <<EOF
#!/bin/sh
# antigravity-cli-unlocker egress launcher: one process, no shell parsing of
# user data beyond this file. systemd restarts it on failure.
set -eu
. ${ENV_FILE}
exec /usr/bin/microsocks -i 0.0.0.0 -p "\$PORT" -u "\$PROXY_USER" -P "\$PROXY_PASSWORD"
EOF
}

render_unit() {
    cat <<EOF
[Unit]
Description=Antigravity egress SOCKS5 (microsocks)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
ExecStart=${LAUNCHER}
Restart=always
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
RestrictAddressFamilies=AF_INET AF_INET6
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF
}

print_client_commands() {
    local url="socks5h://${URL_USER}:${URL_PASS}@${PUBLIC_IP}:${PORT}"
    echo ""
    echo "  Локальная машина (не VPS):"
    echo ""
    echo "    antigravity-unlock egress add '${url}' --label vps"
    echo "    antigravity-unlock egress test --model gemini-3.8-flash-low"
    echo "    antigravity-unlock egress enable"
    echo ""
    echo "  Для голого agy (не только antigravity-unlock run):"
    echo "    antigravity-unlock patch --only proxy_var_isolation"
    echo "    antigravity-unlock egress hook install"
    echo ""
}

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "=== DRY RUN: nothing will be changed ==="
    echo ""
    echo "--- ${ENV_FILE} ---"
    render_env
    echo "--- ${LAUNCHER} ---"
    render_launcher
    echo "--- ${UNIT} ---"
    render_unit
    echo "--- end of config ---"
    print_client_commands
    echo "  Firewall plan: allow ${ALLOW} -> ${PORT}/tcp (ufw/firewalld)"
    echo "  Порт ${PORT}/tcp всё равно нужно открыть в firewall облака."
    exit 0
fi

[[ "$(id -u)" -eq 0 ]] || die "run as root: sudo bash $0"
command -v apt-get >/dev/null 2>&1 || die "this script supports Ubuntu/Debian (apt-get not found)"
command -v systemctl >/dev/null 2>&1 || die "systemd is required"

info "installing microsocks"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq microsocks curl >/dev/null

if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
    info "creating service group ${SERVICE_USER}"
    groupadd --system "$SERVICE_USER"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    info "creating service user ${SERVICE_USER}"
    useradd --system --no-create-home --shell /usr/sbin/nologin \
        --gid "$SERVICE_USER" "$SERVICE_USER"
fi

info "writing ${LAUNCHER}"
render_launcher > "$LAUNCHER"
chmod 755 "$LAUNCHER"
chown root:root "$LAUNCHER"

info "writing ${ENV_FILE}"
render_env > "$ENV_FILE"
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

info "writing ${UNIT}"
render_unit > "$UNIT"
chmod 644 "$UNIT"

info "starting the service"
systemctl daemon-reload
systemctl enable antigravity-egress.service >/dev/null 2>&1 || true
systemctl restart antigravity-egress.service
sleep 1
if ! systemctl is-active --quiet antigravity-egress.service; then
    echo "antigravity-egress failed to start. Recent journal:" >&2
    journalctl -u antigravity-egress.service -n 20 --no-pager >&2 || true
    exit 1
fi
ok "SOCKS5 is running on 0.0.0.0:${PORT} (user ${PROXY_USER})"

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    if [[ "$ALLOW" == "0.0.0.0/0" ]]; then
        info "opening ${PORT}/tcp in ufw for everyone"
        ufw allow "${PORT}/tcp" >/dev/null
    else
        info "opening ${PORT}/tcp in ufw only for ${ALLOW}"
        ufw allow from "$ALLOW" to any port "$PORT" proto tcp >/dev/null
    fi
    ok "ufw rule added"
fi
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    if [[ "$ALLOW" == "0.0.0.0/0" ]]; then
        firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null
    else
        firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=${ALLOW} port port=${PORT} protocol=tcp accept" >/dev/null
    fi
    firewall-cmd --reload >/dev/null
    ok "firewalld rule added"
fi

if [[ "$RUN_TEST" -eq 1 ]]; then
    info "testing the proxy locally"
    body="$(curl -fsS --max-time 20 --socks5-hostname "127.0.0.1:${PORT}" \
        --proxy-user "${PROXY_USER}:${PASSWORD}" https://ipinfo.io/json 2>/dev/null || true)"
    if [[ -n "$body" ]]; then
        summary="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("country"), d.get("city"), d.get("ip"))' <<<"$body" 2>/dev/null || echo "$body")"
        ok "proxy answered; VPS exits as: ${summary}"
        case "$summary" in
            RU*|BY*|IR*|CU*|KP*|SY*|CR*)
                warn "VPS is in a blocked region (${summary%% *}). Gemini will still be refused."
                warn "Create the VPS in a supported country (Frankfurt, Amsterdam, Helsinki, ...)."
                ;;
        esac
    else
        warn "local test failed. Check: journalctl -u antigravity-egress.service -n 50 --no-pager"
    fi
fi

umask 077
CREDS="/root/antigravity-egress.txt"
cat > "$CREDS" <<EOF
# antigravity-cli-unlocker egress credentials
# generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
PROXY_HOST=$PUBLIC_IP
PROXY_PORT=$PORT
PROXY_USER=$PROXY_USER
PROXY_PASSWORD=$PASSWORD
PROXY_URL=socks5h://${URL_USER}:${URL_PASS}@${PUBLIC_IP}:${PORT}
EOF
chmod 600 "$CREDS"

echo ""
ok "Готово. SOCKS5: ${PUBLIC_IP}:${PORT}"
echo "  Креды сохранены в ${CREDS} (chmod 600)."
print_client_commands
echo "  ВАЖНО: открой ${PORT}/tcp в firewall облака (Oracle VCN security list,"
echo "  AWS security group, Hetzner firewall и т.п.) - иначе снаружи не подключиться."
echo ""
echo "  Безопасность: SOCKS5-пароль идёт по сети в открытом виде (RFC 1929),"
echo "  но трафик до Google остаётся TLS. Ставь сильный пароль и по возможности"
echo "  ограничь --allow своим статическим IP: публичный прокси легко абьюзят."
