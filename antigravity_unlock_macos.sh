#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v2.3.0                     ║
# ║   Обход региональных ограничений, фиксация версии & автозапуск (macOS)║
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

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}====================================================================${NC}"
    echo -e "${CYAN}${BOLD}                  Antigravity CLI Unlocker v2.3.0 (macOS)            ${NC}"
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
    if command -v python3 >/dev/null 2>&1; then
        python3 "$PYTHON_CORE" "$@"
    elif command -v python >/dev/null 2>&1; then
        python "$PYTHON_CORE" "$@"
    else
        err "Интерпретатор python3 не найден в системе."
        print_issues_help
        exit 1
    fi
}

step_dns_macos() {
    step 2 "Настройка системной DNS-маршрутизации (macOS networksetup)"
    info "Установка DNS-серверов $DNS_PRIMARY, $DNS_SECONDARY на сетевые службы..."

    local service
    service=$(networksetup -listallnetworkservices 2>/dev/null | grep -v "\*" | head -n 1 || echo "Wi-Fi")
    
    if [[ -n "$service" ]]; then
        info "Настройка интерфейса '$service' (может потребоваться sudo)..."
        if sudo networksetup -setdnsservers "$service" "$DNS_PRIMARY" "$DNS_SECONDARY" 2>/dev/null; then
            sudo dscacheutil -flushcache 2>/dev/null || true
            sudo killall -HUP mDNSResponder 2>/dev/null || true
            ok "DNS-серверы успешно применены к интерфейсу '$service'."
            ok "Кэш DNS в macOS (mDNSResponder) очищен."
        else
            warn "Не удалось автоматически изменить DNS. Вы можете сделать это вручную в Системных настройках -> Сеть -> DNS."
        fi
    fi
}

step_restore_dns_macos() {
    local service
    service=$(networksetup -listallnetworkservices 2>/dev/null | grep -v "\*" | head -n 1 || echo "Wi-Fi")
    if [[ -n "$service" ]]; then
        sudo networksetup -setdnsservers "$service" "Empty" 2>/dev/null && ok "DNS сброшены к значениям по умолчанию."
        sudo dscacheutil -flushcache 2>/dev/null || true
        sudo killall -HUP mDNSResponder 2>/dev/null || true
    fi
}

main() {
    print_banner

    case "${1:-}" in
        --restore)
            run_python_core restore
            step_restore_dns_macos
            echo -e "\n${GREEN}[ОК] Восстановление системы завершено.${NC}\n"
            exit 0
            ;;
        --autostart|--install-autostart)
            step 1 "Установка LaunchAgent автозапуска Guardian (com.antigravity.unlocker.guardian)"
            run_python_core autostart install
            step_dns_macos
            echo -e "\n${GREEN}[ОК] Автозапуск демона Guardian через launchd настроен.${NC}\n"
            exit 0
            ;;
        --remove-autostart|--uninstall-autostart)
            step 1 "Удаление LaunchAgent Guardian"
            run_python_core autostart remove
            echo -e "\n${GREEN}[ОК] Автозапуск удален.${NC}\n"
            exit 0
            ;;
        --guardian)
            step 1 "Запуск Guardian демона"
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

    step 1 "Обработка бинарника и фиксация версии 1.1.9 через Python Core (macOS)"
    run_python_core "$@"

    step_dns_macos

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
