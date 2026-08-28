#!/bin/bash
# ============================================
# TEST #1: geohide.ru SNI proxy via /etc/hosts
# ============================================
# Бинарный патч + /etc/hosts pinning к работающему SNI-прокси.
# SNI-прокси принимает TLS с SNI daily-cloudcode-pa.googleapis.com
# и пересылает запрос на реальный сервер Google.
#
# Безопасно: откат одной командой (см. cleanup).

set -e

PROXY_IP="45.155.204.190"
PROXY_IP2="37.230.192.51"
TARGETS=(
    "daily-cloudcode-pa.googleapis.com"
    "cloudcode-pa.googleapis.com"
)

echo "=== Test #1: geohide.ru hosts pinning ==="
echo ""

# Backup
cp /etc/hosts /etc/hosts.bak.agy
echo "[+] Backup: /etc/hosts.bak.agy"

# Add entries
echo "" >> /etc/hosts
echo "# AGY unlocker: geohide SNI proxy (test #1)" >> /etc/hosts
for target in "${TARGETS[@]}"; do
    echo "$PROXY_IP $target" >> /etc/hosts
done
echo "[+] Added hosts entries"

# Verify
echo ""
echo "DNS resolution:"
for target in "${TARGETS[@]}"; do
    ip=$(getent hosts "$target" | awk '{print $1}')
    echo "  $target -> $ip"
done

# Test
echo ""
echo "Running agy test..."
timeout 20 /home/nwk/.local/bin/agy -p "respond with just: hosts pin ok" --output-format json 2>/dev/null | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
status = d.get('status', '?')
resp = d.get('response', 'none')[:80]
dur = d.get('duration_seconds', '?')
print(f'  Status: {status}')
print(f'  Response: {resp}')
print(f'  Duration: {dur}s')
if status == 'SUCCESS':
    print('  ✅ TEST #1 PASSED!')
else:
    print('  ❌ TEST #1 FAILED')
" 2>/dev/null || echo "  ❌ Timeout/Error"

echo ""
echo "=== Cleanup (run after test): ==="
echo "  sudo cp /etc/hosts.bak.agy /etc/hosts"
echo ""
echo "=== Auto-cleanup in 60 seconds... ==="
sleep 60
cp /etc/hosts.bak.agy /etc/hosts
echo "[+] Hosts restored"
