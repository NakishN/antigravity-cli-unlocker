#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v1.5.0                     ║
# ║        Патч eligibility-гейта, диагностика & автозапуск (Linux)      ║
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
    echo -e "${CYAN}${BOLD}                  Antigravity CLI Unlocker v${VERSION}                   ${NC}"
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

# ── Удалено в 1.5.0 ────────────────────────────────────────────────────────
# Раньше здесь был step_dns: systemd-resolved drop-in, направлявший CloudCode
# на Smart DNS (xbox-dns.ru, 111.88.96.50/51).  Проверка 2026-09-20 показала,
# что эти резолверы возвращают для cloudcode-pa.googleapis.com и
# daily-cloudcode-pa.googleapis.com те же самые реальные IP Google, что и
# 8.8.8.8 — подмены нет.  Подменялся только generativelanguage, который agy не
# использует.  Шаг менял системный DNS, требуя sudo, и не давал ничего.
#
# Eligibility-гейт — это клиентская проверка серверного protobuf-поля, и её
# снимает патч бинарника.  Проверено на agy 1.2.7 с российского IP без VPN,
# прокси и подмены DNS: `agy -p` возвращает реальные ответы модели.
# ───────────────────────────────────────────────────────────────────────────

step_restore_ipv4() {
    local gai_conf="/etc/gai.conf"
    local marker="# antigravity-unlocker: prefer IPv4"
    if [[ -f "$gai_conf" ]] && grep -q "$marker" "$gai_conf" 2>/dev/null; then
        if sudo -n sed -i "/$marker/,+2d" "$gai_conf" 2>/dev/null; then
            ok "IPv4 приоритет удалён из $gai_conf"
        else
            warn "Нужны права root. Выполните вручную:"
            echo -e "       ${BOLD}sudo sed -i '/$marker/,+2d' $gai_conf${NC}"
        fi
    fi
}

step_report_legacy() {
    # Только чтение и без sudo: основной сценарий разблокировки не должен
    # требовать root и не должен блокироваться на запросе пароля.  Удаление —
    # за явным --cleanup-legacy / --restore.
    local conf_file="/etc/systemd/resolved.conf.d/antigravity-unlock.conf"
    local found=0

    if [[ -f "$conf_file" ]]; then
        warn "Найден устаревший Smart DNS drop-in: $conf_file"
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

step_cleanup_legacy() {
    # Явная очистка.  sudo -n: если пароля нет, сообщаем и выходим, а не висим.
    local conf_file="/etc/systemd/resolved.conf.d/antigravity-unlock.conf"

    if [[ -f "$conf_file" ]]; then
        info "Удаляю устаревший Smart DNS drop-in: $conf_file"
        if sudo -n bash -c "
            rm -f '$conf_file'
            systemctl restart systemd-resolved 2>/dev/null || true
            resolvectl flush-caches 2>/dev/null || true
        " 2>/dev/null; then
            ok "Устаревшие правила DNS-маршрутизации удалены."
        else
            warn "Нужны права root. Выполните вручную:"
            echo -e "       ${BOLD}sudo rm '$conf_file' && sudo systemctl restart systemd-resolved${NC}"
        fi
    else
        info "Smart DNS drop-in не найден — очищать нечего."
    fi

    if grep -qE "cloudcode-pa\.googleapis\.com|generativelanguage\.googleapis\.com" /etc/hosts 2>/dev/null; then
        warn "В /etc/hosts остались пины CloudCode. Выполните:"
        echo -e "       ${BOLD}sudo python3 \"$PYTHON_CORE\" setup remove${NC}"
    fi
}

step_restore_ipv4() {
    local gai_conf="/etc/gai.conf"
    local marker="# antigravity-unlocker: prefer IPv4"
    if [[ -f "$gai_conf" ]] && grep -q "$marker" "$gai_conf" 2>/dev/null; then
        sudo sed -i "/$marker/,+2d" "$gai_conf" 2>/dev/null \
            && ok "IPv4 приоритет удалён из $gai_conf"
    fi
}

main() {
    print_banner

    case "${1:-}" in
        --restore)
            run_python_core restore
            step_cleanup_legacy
            step_restore_ipv4
            echo -e "\n${GREEN}[ОК] Восстановление системы завершено.${NC}\n"
            exit 0
            ;;
        --doctor)
            shift
            run_python_core doctor "$@"
            exit $?
            ;;
        --autostart|--install-autostart)
            step 1 "Установка службы автозапуска Guardian (systemd user unit)"
            run_python_core autostart install
            echo ""
            ok "Guardian будет перепатчивать agy после каждого автообновления."
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
        --cleanup-legacy)
            step_cleanup_legacy
            exit 0
            ;;
    esac

    step 1 "Патч установленного бинарника agy"
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
