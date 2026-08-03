#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  Antigravity CLI Unlocker v2.1                       ║
# ║          Regional Access & DNS Routing for Linux (Ubuntu)            ║
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

AGY_BIN=""
BACKUP_DIR="$HOME/.local/share/antigravity-unlocker"
BACKUP_FILE="$BACKUP_DIR/agy.original.bak"

DNS_PRIMARY="111.88.96.50"
DNS_SECONDARY="111.88.96.51"
DNS_PRIMARY_V6="2a00:ab00:1233:26::50"
DNS_SECONDARY_V6="2a00:ab00:1233:26::51"

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}====================================================================${NC}"
    echo -e "${CYAN}${BOLD}                  Antigravity CLI Unlocker v2.1                      ${NC}"
    echo -e "${CYAN}${BOLD}          Regional Access & DNS Routing for Linux (Ubuntu)          ${NC}"
    echo -e "${CYAN}${BOLD}====================================================================${NC}"
    echo ""
}

ok()   { echo -e "  ${GREEN}[OK]${NC} $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "  ${RED}[ERROR]${NC} $*"; }
info() { echo -e "  ${BLUE}[INFO]${NC} $*"; }
step() { echo -e "\n${BOLD}[$1/3] $2${NC}"; }

print_issues_help() {
    echo ""
    echo -e "  ${YELLOW}Support & Troubleshooting:${NC}"
    echo -e "  ${CYAN}$ISSUES_URL${NC}"
    echo ""
}

get_agy_version() {
    local bin="${1:-$AGY_BIN}"
    [[ -n "$bin" && -f "$bin" ]] || return 1
    if [[ "$bin" == "$AGY_BIN" || -z "$AGY_BIN" ]]; then
        "$bin" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 && return 0
    fi
    strings "$bin" 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
}

find_agy() {
    local candidates=(
        "$HOME/.local/bin/agy"
        "/usr/local/bin/agy"
        "/usr/bin/agy"
        "$(command -v agy 2>/dev/null || true)"
    )
    for path in "${candidates[@]}"; do
        if [[ -n "$path" && -f "$path" && -x "$path" ]]; then
            AGY_BIN="$path"
            return 0
        fi
    done
    return 1
}

step_backup() {
    step 1 "Binary Backup"

    if ! find_agy; then
        err "Target binary 'agy' not found on system."
        info "Install Antigravity CLI from https://antigravity.google/docs"
        info "or specify explicit path: AGY_BIN=/path/to/agy $0"
        print_issues_help
        exit 1
    fi

    info "Target binary located: $AGY_BIN"
    mkdir -p "$BACKUP_DIR"

    local current_ver backup_ver
    current_ver="$(get_agy_version "$AGY_BIN" || echo unknown)"
    backup_ver="$(get_agy_version "$BACKUP_FILE" 2>/dev/null || echo none)"

    if [[ -f "$BACKUP_FILE" && "$current_ver" != "$backup_ver" && "$current_ver" != unknown ]]; then
        warn "Binary update detected: $backup_ver -> $current_ver"
        cp "$AGY_BIN" "$BACKUP_FILE"
        ok "Backup updated to v$current_ver"
    elif [[ -f "$BACKUP_FILE" ]]; then
        ok "Backup verified (v$backup_ver): $BACKUP_FILE"
    else
        cp "$AGY_BIN" "$BACKUP_FILE"
        ok "Backup created (v$current_ver): $BACKUP_FILE"
    fi
}

step_patch_binary() {
    step 2 "Machine Code Gate Patching"

    local result
    result=$(AGY_BIN="$AGY_BIN" python3 << 'PYEOF'
import sys, os, re

agy_path = os.environ.get('AGY_BIN', os.path.expanduser('~/.local/bin/agy'))
try:
    with open(agy_path, 'rb') as f:
        data = bytearray(f.read())
except Exception as e:
    print(f"ERROR:Cannot read file {agy_path}: {e}")
    sys.exit(1)

GATES = [
    (
        "x64 eligibility gate",
        re.compile(rb'\x48\x85\xc0\x0f\x84....\x80\x78\x08\x00\x0f\x85....', re.S),
        re.compile(rb'\x48\x85\xc0\x0f\x84....\x48\x85\xc0\x90\x0f\x85....', re.S),
        b'\x48\x85\xc0\x90',
        9,
    ),
    (
        "arm64 eligibility gate",
        re.compile(rb'...\xb5...\xb4\x01\x20\x40\x39...\x37', re.S),
        re.compile(rb'...\xb5...\xb4\x21\x00\x80\x52...\x37', re.S),
        b'\x21\x00\x80\x52',
        8,
    ),
]

applied = []
already = []
missing = []

for label, sig, patched, fix, offset in GATES:
    patched_hits = list(patched.finditer(data))
    if patched_hits:
        already.append(f'{label} ({len(patched_hits)}x)')
        continue
    hits = [m.start() + offset for m in sig.finditer(data)]
    if not hits:
        missing.append(label)
        continue
    for off in hits:
        data[off:off + len(fix)] = fix
    applied.append(f'{label} ({len(hits)}x)')

if not applied:
    if already:
        print("ALREADY:" + "|".join(already))
    else:
        print("MISSING:" + "|".join(missing or ["no gate signatures matched"]))
    sys.exit(0)

tmp_path = agy_path + '.patching_tmp'
try:
    with open(tmp_path, 'wb') as f:
        f.write(data)
    orig_mode = os.stat(agy_path).st_mode
    os.chmod(tmp_path, orig_mode)
    os.replace(tmp_path, agy_path)
    print("OK:" + "|".join(applied))
except Exception as e:
    if os.path.exists(tmp_path):
        try: os.unlink(tmp_path)
        except Exception: pass
    print(f"ERROR:{e}")
    sys.exit(1)
PYEOF
)

    case "${result%%:*}" in
        OK)
            local patches="${result#OK:}"
            IFS='|' read -ra parts <<< "$patches"
            for p in "${parts[@]}"; do
                ok "Patch applied successfully: $p"
            done
            ;;
        ALREADY)
            local items="${result#ALREADY:}"
            IFS='|' read -ra parts <<< "$items"
            for p in "${parts[@]}"; do
                ok "Patch already applied: $p"
            done
            ;;
        MISSING)
            err "Eligibility gate signatures not found."
            info "Check binary version: agy --version"
            print_issues_help
            ;;
        ERROR)
            err "Failed writing patched binary: ${result#ERROR:}"
            warn "Ensure agy is not currently running."
            print_issues_help
            ;;
    esac
}

step_dns() {
    step 3 "System DNS Routing Configuration"

    info "DNS Servers: $DNS_PRIMARY, $DNS_SECONDARY"

    local conf_dir="/etc/systemd/resolved.conf.d"
    local conf_file="$conf_dir/antigravity-unlock.conf"

    if [[ -f "$conf_file" ]] && grep -q "111.88.96.50" "$conf_file" 2>/dev/null; then
        ok "systemd-resolved configuration already active: $conf_file"
        return 0
    fi

    if ! systemctl is-active --quiet systemd-resolved 2>/dev/null; then
        warn "systemd-resolved service is inactive. Skipping automated DNS setup."
        warn "Enable service: sudo systemctl enable --now systemd-resolved"
        return 0
    fi

    info "Elevated permissions required to write $conf_file"
    echo ""

    local tmp_conf
    tmp_conf=$(mktemp /tmp/antigravity-dns-XXXXXX.conf)
    cat > "$tmp_conf" << EOF
# Antigravity CLI Unlocker v2.1 Configuration
[Resolve]
DNS=$DNS_PRIMARY $DNS_SECONDARY
FallbackDNS=$DNS_PRIMARY_V6 $DNS_SECONDARY_V6
Domains=~googleapis.com ~googleusercontent.com ~accounts.google.com ~google ~goog
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
        ok "DNS configuration created: $conf_file"
        ok "systemd-resolved restarted, DNS cache flushed"
    else
        rm -f "$tmp_conf"
        err "Failed writing systemd-resolved configuration."
        print_issues_help
    fi

    sleep 1
    if curl -s --max-time 5 -o /dev/null -w "%{http_code}" \
        https://generativelanguage.googleapis.com/ 2>/dev/null | grep -qE "^(200|400|403|404)$"; then
        ok "Google API connectivity verified."
    else
        warn "Connectivity check timed out. Start agy to verify status."
    fi
}

step_restore() {
    echo ""
    echo -e "${BOLD}${RED}Restoring Original System State${NC}"
    echo ""

    if [[ -f "$BACKUP_FILE" ]]; then
        find_agy || AGY_BIN="$HOME/.local/bin/agy"
        cp "$BACKUP_FILE" "$AGY_BIN"
        ok "Original agy binary restored from backup."
    else
        warn "Backup file not found: $BACKUP_FILE"
    fi

    local conf_file="/etc/systemd/resolved.conf.d/antigravity-unlock.conf"
    if [[ -f "$conf_file" ]]; then
        sudo bash -c "
            rm -f '$conf_file'
            systemctl restart systemd-resolved 2>/dev/null || true
            resolvectl flush-caches 2>/dev/null || true
        " && ok "DNS routing rules removed."
    fi

    ok "System restore complete."
}

main() {
    print_banner

    if [[ "${1:-}" == "--restore" ]]; then
        step_restore
        exit 0
    fi

    step_backup
    step_patch_binary
    step_dns

    echo ""
    echo -e "${GREEN}${BOLD}====================================================================${NC}"
    echo -e "${GREEN}${BOLD}             Antigravity CLI Unlock Completed                        ${NC}"
    echo -e "${GREEN}${BOLD}====================================================================${NC}"
    echo ""
    local ver
    ver="$(get_agy_version || echo "?")"
    echo -e "  Status:  ${BOLD}agy v$ver${NC} (Ready)"
    echo -e "  Execute: ${BOLD}agy${NC}"
    echo ""
    echo -e "  Restore: bash \"$(realpath "$0")\" --restore"
    echo -e "  Backup:  $BACKUP_FILE"
    echo -e "  Support: $ISSUES_URL"
    echo ""
}

main "$@"
