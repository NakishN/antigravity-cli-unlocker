#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v1.5.0                     ║
# ║      Патч eligibility-гейта, диагностика & автозапуск (macOS)        ║
# ╚══════════════════════════════════════════════════════════════════════╝

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

VERSION="1.5.0"
ISSUES_URL="https://github.com/NakishN/antigravity-cli-unlocker/issues"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CORE="$SCRIPT_DIR/antigravity_unlock.py"

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}====================================================================${NC}"
    echo -e "${CYAN}${BOLD}              Antigravity CLI Unlocker v${VERSION} (macOS)               ${NC}"
    echo -e "${CYAN}${BOLD}     Патч eligibility-гейта, диагностика и защита от автообновлений  ${NC}"
    echo -e "${CYAN}${BOLD}====================================================================${NC}"
    echo ""
}

ok()   { echo -e "  ${GREEN}[ОК]${NC} $*"; }
warn() { echo -e "  ${YELLOW}[ВНИМАНИЕ]${NC} $*"; }
err()  { echo -e "  ${RED}[ОШИБКА]${NC} $*"; }
info() { echo -e "  ${BLUE}[ИНФО]${NC} $*"; }
step() { echo -e "\n${BOLD}[$1] $2${NC}"; }

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

# ── Удалено в 1.5.0 ────────────────────────────────────────────────────────
# Раньше здесь был step_dns_macos: `networksetup -setdnsservers` прописывал
# Smart DNS (xbox-dns.ru, 111.88.96.50/51) на основной сетевой сервис, то есть
# менял DNS всей системе.  Проверка 2026-09-20 показала, что эти резолверы
# возвращают для cloudcode-pa.googleapis.com те же реальные IP Google, что и
# 8.8.8.8 — подмены нет, шаг не давал ничего, кроме побочных эффектов.
#
# Eligibility-гейт — клиентская проверка серверного protobuf-поля, её снимает
# патч бинарника.  Проверено на agy 1.2.7 из заблокированного региона без VPN,
# прокси и подмены DNS.
#
# step_restore_dns_macos ниже СОХРАНЁН намеренно: у тех, кто запускал прежние
# версии, системный DNS уже изменён, и его надо уметь вернуть.
# ───────────────────────────────────────────────────────────────────────────

_primary_service() {
    networksetup -listallnetworkservices 2>/dev/null | grep -v "\*" | head -n 1 || echo "Wi-Fi"
}

_has_legacy_dns() {
    local service="$1"
    networksetup -getdnsservers "$service" 2>/dev/null | grep -qE "111\.88\.96\.(50|51)"
}

step_report_legacy() {
    # Только чтение и без sudo: основной сценарий разблокировки не должен
    # требовать root и не должен блокироваться на запросе пароля.
    local service found=0
    service=$(_primary_service)

    if [[ -n "$service" ]] && _has_legacy_dns "$service"; then
        warn "На интерфейсе '$service' прописан Smart DNS (xbox-dns.ru) версиями <=1.4.x"
        found=1
    fi

    if grep -qE "cloudcode-pa\.googleapis\.com|generativelanguage\.googleapis\.com" /etc/hosts 2>/dev/null; then
        warn "Найдены устаревшие пины CloudCode в /etc/hosts"
        found=1
    fi

    if [[ "$found" -eq 1 ]]; then
        echo ""
        echo -e "  Это настройки версий <=1.4.x. Они больше не нужны и могут мешать:"
        echo -e "  Smart DNS не подменяет CloudCode, а пин в hosts указывает на"
        echo -e "  эндпоинт, который не завершает TLS-рукопожатие."
        echo ""
        echo -e "  Удалить (потребуется sudo):"
        echo -e "    ${BOLD}bash \"$(realpath "$0")\" --cleanup-legacy${NC}"
        echo -e "    ${BOLD}sudo python3 \"$PYTHON_CORE\" setup remove${NC}"
        echo ""
    fi
}

step_restore_dns_macos() {
    local service
    service=$(_primary_service)
    if [[ -z "$service" ]]; then
        return 0
    fi

    if ! _has_legacy_dns "$service"; then
        info "Системный DNS интерфейса '$service' не менялся этим инструментом — сброс не нужен."
        return 0
    fi

    info "Найден Smart DNS (xbox-dns.ru) на интерфейсе '$service' — сбрасываю к DHCP."
    if sudo -n networksetup -setdnsservers "$service" "Empty" 2>/dev/null; then
        sudo -n dscacheutil -flushcache 2>/dev/null || true
        sudo -n killall -HUP mDNSResponder 2>/dev/null || true
        ok "Системный DNS сброшен к значениям по умолчанию."
    else
        warn "Нужны права root. Выполните вручную:"
        echo -e "       ${BOLD}sudo networksetup -setdnsservers \"$service\" Empty${NC}"
        echo -e "       ${BOLD}sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder${NC}"
    fi
}

step_cleanup_hosts() {
    if ! grep -qE "cloudcode-pa\.googleapis\.com|generativelanguage\.googleapis\.com" /etc/hosts 2>/dev/null; then
        info "Пинов CloudCode в /etc/hosts нет — очищать нечего."
        return 0
    fi
    warn "В /etc/hosts остались пины CloudCode. Выполните (нужен root):"
    echo -e "       ${BOLD}sudo python3 \"$PYTHON_CORE\" setup remove${NC}"
}

main() {
    print_banner

    case "${1:-}" in
        --restore)
            run_python_core restore
            step_restore_dns_macos
            step_cleanup_hosts
            echo -e "\n${GREEN}[ОК] Восстановление системы завершено.${NC}\n"
            exit 0
            ;;
        --doctor)
            shift
            run_python_core doctor "$@"
            exit $?
            ;;
        --cleanup-legacy)
            step_restore_dns_macos
            step_cleanup_hosts
            exit 0
            ;;
        --autostart|--install-autostart)
            step 1 "Установка LaunchAgent автозапуска Guardian (com.antigravity.unlocker.guardian)"
            run_python_core autostart install
            echo ""
            ok "Guardian будет перепатчивать agy после каждого автообновления."
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

    step 1 "Патч установленного бинарника agy (macOS)"
    run_python_core "$@"

    step 2 "Проверка устаревших настроек (<=1.4.x)"
    step_report_legacy

    echo ""
    echo -e "${GREEN}${BOLD}====================================================================${NC}"
    echo -e "${GREEN}${BOLD}             Разблокировка Antigravity CLI завершена                ${NC}"
    echo -e "${GREEN}${BOLD}====================================================================${NC}"
    echo ""
    echo -e "  Запуск:         ${BOLD}agy${NC}"
    echo -e "  Диагностика:    bash \"$(realpath "$0")\" --doctor"
    echo -e "  Автозапуск:     bash \"$(realpath "$0")\" --autostart"
    echo -e "  Удаление авто:  bash \"$(realpath "$0")\" --remove-autostart"
    echo -e "  Откат:          bash \"$(realpath "$0")\" --restore"
    echo -e "  Тест:           bash \"$(realpath "$0")\" patch --dry-run"
    echo -e "  Поддержка:      $ISSUES_URL"
    echo ""
    warn "agy самообновляется и затирает патч. Установите автозапуск Guardian:"
    echo -e "       bash \"$(realpath "$0")\" --autostart"
    echo ""
}

main "$@"
