#!/bin/bash
# ============================================
# TEST #2: Tor SOCKS5 proxy with US exit nodes
# ============================================
# Устанавливает Tor, настраивает exit-ноды в US/DE/NL,
# запускает agy через SOCKS5 прокси.
#
# Tor обходит IP-блокировку, меняя exit-ноду.
# Медленно (~3-5 сек на запрос), но бесплатно.

set -e

echo "=== Test #2: Tor SOCKS5 proxy ==="
echo ""

# Install Tor if not present
if ! command -v tor &>/dev/null; then
    echo "[+] Installing Tor..."
    apt-get install -y tor
fi

# Configure Tor for US/EU exit nodes
TORRC="/etc/tor/torrc"
cp "$TORRC" "${TORRC}.bak.agy" 2>/dev/null || true

cat > /tmp/torrc.agy << 'EOF'
# AGY unlocker Tor config
SocksPort 9050
ExitNodes {us},{de},{nl},{fr},{gb}
StrictNodes 1
# Speed optimizations
MaxCircuitDirtiness 600
CircuitBuildTimeout 15
EOF

cp /tmp/torrc.agy "$TORRC"
echo "[+] Tor configured with US/DE/NL/FR/GB exit nodes"

# Start Tor
systemctl restart tor
echo "[+] Tor restarted, waiting for circuit..."
sleep 10

# Verify Tor is running
if ! systemctl is-active --quiet tor; then
    echo "❌ Tor failed to start"
    exit 1
fi

# Check exit IP
echo ""
echo "Tor exit IP:"
curl -s --proxy socks5h://127.0.0.1:9050 https://ipinfo.io/json 2>/dev/null | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
print(f'  IP: {d.get(\"ip\")}')
print(f'  Country: {d.get(\"country\")}')
print(f'  Org: {d.get(\"org\")}')
" 2>/dev/null || echo "  Could not check IP"

# Test agy through Tor
echo ""
echo "Running agy test through Tor..."
timeout 30 env \
    HTTPS_PROXY=socks5h://127.0.0.1:9050 \
    HTTP_PROXY=socks5h://127.0.0.1:9050 \
    /home/nwk/.local/bin/agy -p "respond with just: tor proxy ok" --output-format json 2>/dev/null | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
status = d.get('status', '?')
resp = d.get('response', 'none')[:80]
dur = d.get('duration_seconds', '?')
print(f'  Status: {status}')
print(f'  Response: {resp}')
print(f'  Duration: {dur}s')
if status == 'SUCCESS':
    print('  ✅ TEST #2 PASSED!')
else:
    print('  ❌ TEST #2 FAILED')
" 2>/dev/null || echo "  ❌ Timeout/Error"

echo ""
echo "=== Cleanup: ==="
echo "  sudo cp ${TORRC}.bak.agy $TORRC && sudo systemctl restart tor"
