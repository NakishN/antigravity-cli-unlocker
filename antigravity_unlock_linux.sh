#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v2.3.0                     ║
# ║   Обход региональных ограничений, фиксация версии & автозапуск (Linux)║
# ╚══════════════════════════════════════════════════════════════════════╝

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ISSUES_URL="https://github.com/NakishN/antigravity-cli-unlocker/issues"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CORE="$SCRIPT_DIR/antigravity_unlock.py"

DNS_PRIMARY="111.88.96.50"
DNS_SECONDARY="111.88.96.51"
DNS_PRIMARY_V6="2a00:ab00:1233:26::50"
DNS_SECONDARY_V6="2a00:ab00:1233:26::51"

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}====================================================================${NC}"
    echo -e "${CYAN}${BOLD}                  Antigravity CLI Unlocker v2.3.0                    ${NC}"
    echo -e "${CYAN}${BOLD}    Обход региональных ограничений, фиксация 1.1.9 & автозапуск  ${NC}"
    echo -e "${CYAN}${BOLD}====================================================================${NC}"
    echo ""
}

ok()   { echo -e "  ${GREEN}[ОК]${NC} $*"; }
warn() { echo -e "  ${YELLOW}[ВНИМАНИЕ]${NC} $*"; }
err()  { echo -e "  ${RED}[ОШИБКА]${NC} $*"; }
info() { echo -e "  ${BLUE}[ИНФО]${NC} $*"; }
step() { echo -e "\n${BOLD}[$1/2] $2${NC}"; }

print_issues_help() {
    echo ""
    echo -e "  ${YELLOW}Поддержка и решение проблем:${NC}"
    echo -e "  ${CYAN}$ISSUES_URL${NC}"
    echo ""
}

run_python_core() {
    if ! command -v python3 >/dev/null 2>&1; then
        err "Интерпретатор python3 не найден в системе."
        print_issues_help
        exit 1
    fi

    if [[ ! -f "$PYTHON_CORE" ]]; then
        err "Модуль ядра '$PYTHON_CORE' не найден."
        print_issues_help
        exit 1
    fi

    python3 "$PYTHON_CORE" "$@"
}

step_dns() {
    step 2 "Настройка системной DNS-маршрутизации"

    info "Адреса DNS-серверов: $DNS_PRIMARY, $DNS_SECONDARY"

    local conf_dir="/etc/systemd/resolved.conf.d"
    local conf_file="$conf_dir/antigravity-unlock.conf"

    if [[ -f "$conf_file" ]] && grep -q "111.88.96.50" "$conf_file" 2>/dev/null; then
        ok "Конфигурация systemd-resolved уже активна: $conf_file"
        return 0
    fi

    if ! systemctl is-active --quiet systemd-resolved 2>/dev/null; then
        warn "Служба systemd-resolved не активна. Автоматическая настройка DNS пропущена."
        warn "Запустите службу: sudo systemctl enable --now systemd-resolved"
        return 0
    fi

    info "Требуются права root (sudo) для записи $conf_file"
    echo ""

    local tmp_conf
    tmp_conf=$(mktemp /tmp/antigravity-dns-XXXXXX.conf)
    cat > "$tmp_conf" << EOF
# Antigravity CLI Unlocker Configuration
[Resolve]
DNS=$DNS_PRIMARY $DNS_SECONDARY
FallbackDNS=$DNS_PRIMARY_V6 $DNS_SECONDARY_V6
Domains=~googleapis.com ~googleusercontent.com ~google ~goog
EOF

    if sudo bash -c "
        set -e
        mkdir -p '$conf_dir'
        cp '$tmp_conf' '$conf_file'
        chmod 644 '$conf_file'
        systemctl restart systemd-resolved
        resolvectl flush-caches 2>/dev/null || true
    "; then
        rm -f "$tmp_conf"
        ok "Конфигурация DNS создана: $conf_file"
        ok "Служба systemd-resolved перезапущена, кэш DNS очищен"
    else
        rm -f "$tmp_conf"
        err "Ошибка при записи конфигурации systemd-resolved."
        print_issues_help
    fi

    sleep 1
    if curl -s --max-time 5 -o /dev/null -w "%{http_code}" \
        https://generativelanguage.googleapis.com/ 2>/dev/null | grep -qE "^(200|400|403|404)$"; then
        ok "Соединение с Google API успешно подтверждено."
    else
        warn "Таймаут проверки соединения. Запустите agy для проверки работы."
    fi
}

step_restore_dns() {
    local conf_file="/etc/systemd/resolved.conf.d/antigravity-unlock.conf"
    if [[ -f "$conf_file" ]]; then
        sudo bash -c "
            rm -f '$conf_file'
            systemctl restart systemd-resolved 2>/dev/null || true
            resolvectl flush-caches 2>/dev/null || true
        " && ok "Правила DNS-маршрутизации удалены."
    fi
}

main() {
    print_banner

    case "${1:-}" in
        --restore)
            run_python_core restore
            step_restore_dns
            echo -e "\n${GREEN}[ОК] Восстановление системы завершено.${NC}\n"
            exit 0
            ;;
        --autostart|--install-autostart)
            step 1 "Установка службы автозапуска Guardian (systemd user unit)"
            run_python_core autostart install
            step_dns
            echo -e "\n${GREEN}[ОК] Автозапуск демона Guardian успешно настроен.${NC}\n"
            exit 0
            ;;
        --remove-autostart|--uninstall-autostart)
            step 1 "Удаление службы автозапуска Guardian"
            run_python_core autostart remove
            echo -e "\n${GREEN}[ОК] Автозапуск удален.${NC}\n"
            exit 0
            ;;
        --guardian)
            step 1 "Запуск Guardian в фоновом режиме"
            run_python_core guardian
            exit 0
            ;;
        --pin-init)
            shift
            run_python_core pin init "$@"
            exit 0
            ;;
        --pin-check)
            shift
            run_python_core pin check "$@"
            exit 0
            ;;
        --status)
            run_python_core status
            exit 0
            ;;
    esac

    step 1 "Обработка бинарника и обеспечение версии 1.1.9 через Python Core v2.3.0"
    run_python_core "$@"

    step_dns

    echo ""
    echo -e "${GREEN}${BOLD}====================================================================${NC}"
    echo -e "${GREEN}${BOLD}             Разблокировка Antigravity CLI завершена                ${NC}"
    echo -e "${GREEN}${BOLD}====================================================================${NC}"
    echo ""
    echo -e "  Запуск:         ${BOLD}agy${NC}"
    echo -e "  Автозапуск:     bash \"$(realpath "$0")\" --autostart"
    echo -e "  Удаление авто:  bash \"$(realpath "$0")\" --remove-autostart"
    echo -e "  Откат:          bash \"$(realpath "$0")\" --restore"
    echo -e "  Тест:           bash \"$(realpath "$0")\" --dry-run"
    echo -e "  Поддержка:      $ISSUES_URL"
    echo ""
}

main "$@"
