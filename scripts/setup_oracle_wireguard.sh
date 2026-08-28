#!/bin/bash
# ============================================
# TEST #3: Oracle Cloud VPS + WireGuard tunnel
# ============================================
# Oracle Cloud Always Free = ARM VM в US/EU, 10 TB трафика.
# Этот скрипт:
#   1. На Виртуалке в Oracle: ставит WireGuard сервер
#   2. Локально: настраивает WireGuard клиент
#   3. Split-tunnel: только CloudCode трафик через туннель
#
# ТРЕБОВАНИЯ:
#   - Oracle Cloud аккаунт (бесплатный): https://cloud.oracle.com
#   - Создать ARM Ampere инстанс в US регионе (Ashburn/Phoenix)
#   - SSH доступ к инстансу
#
# ИСПОЛЬЗОВАНИЕ:
#   Часть 1 — на Oracle VPS (через SSH):
#     bash setup_oracle_wireguard.sh server
#   Часть 2 — локально:
#     bash setup_oracle_wireguard.sh client <vps_public_ip>

set -e

MODE="${1:-help}"
VPS_IP="${2:-}"

if [ "$MODE" = "help" ]; then
    echo "Usage:"
    echo "  On VPS:  bash setup_oracle_wireguard.sh server"
    echo "  Local:   bash setup_oracle_wireguard.sh client <VPS_PUBLIC_IP>"
    exit 0
fi

if [ "$MODE" = "server" ]; then
    echo "=== Setting up WireGuard SERVER on Oracle VPS ==="

    # Install WireGuard
    apt-get update && apt-get install -y wireguard iptables

    # Generate server keys
    umask 077
    wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
    wg genkey | tee /etc/wireguard/client_private.key | wg pubkey > /etc/wireguard/client_public.key

    SERVER_PRIV=$(cat /etc/wireguard/server_private.key)
    SERVER_PUB=$(cat /etc/wireguard/server_public.key)
    CLIENT_PUB=$(cat /etc/wireguard/client_public.key)
    CLIENT_PRIV=$(cat /etc/wireguard/client_private.key)

    # Server config
    cat > /etc/wireguard/wg0.conf << EOF
[Interface]
PrivateKey = $SERVER_PRIV
Address = 10.8.0.1/24
ListenPort = 51820
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = $CLIENT_PUB
AllowedIPs = 10.8.0.2/32
EOF

    # Enable IP forwarding
    echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf
    sysctl -p

    # Start WireGuard
    systemctl enable wg-quick@wg0
    systemctl start wg-quick@wg0

    # Open firewall
    iptables -I INPUT -p udp --dport 51820 -j ACCEPT
    # Also check if firewalld is running
    if command -v firewall-cmd &>/dev/null; then
        firewall-cmd --permanent --add-port=51820/udp 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
    fi

    echo ""
    echo "=== WireGuard server configured ==="
    echo ""
    echo "Client config (copy this for local setup):"
    echo "---"
    echo "[Interface]"
    echo "PrivateKey = $CLIENT_PRIV"
    echo "Address = 10.8.0.2/32"
    echo "DNS = 8.8.8.8"
    echo ""
    echo "[Peer]"
    echo "PublicKey = $SERVER_PUB"
    echo "Endpoint = $(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_VPS_IP'):51820"
    echo "AllowedIPs = 10.8.0.0/24"
    echo "PersistentKeepalive = 25"
    echo "---"
    echo ""
    echo "Save this config! Run on local machine:"
    echo "  bash setup_oracle_wireguard.sh client $(curl -s ifconfig.me 2>/dev/null || echo 'VPS_IP')"

    exit 0
fi

if [ "$MODE" = "client" ]; then
    if [ -z "$VPS_IP" ]; then
        echo "Usage: bash setup_oracle_wireguard.sh client <VPS_PUBLIC_IP>"
        exit 1
    fi

    echo "=== Setting up WireGuard CLIENT (split-tunnel for CloudCode) ==="

    # Install WireGuard if needed
    if ! command -v wg &>/dev/null; then
        apt-get install -y wireguard
    fi

    # Generate keys if not already done
    if [ ! -f /etc/wireguard/agy_private.key ]; then
        umask 077
        wg genkey | tee /etc/wireguard/agy_private.key | wg pubkey > /etc/wireguard/agy_public.key
    fi

    CLIENT_PRIV=$(cat /etc/wireguard/agy_private.key)

    echo ""
    echo "Send this public key to the VPS to add as peer:"
    echo "  $(cat /etc/wireguard/agy_public.key)"
    echo ""
    echo "On VPS, run:"
    echo "  wg set wg0 peer \$(cat /etc/wireguard/agy_public.key) allowed-ips 10.8.0.2/32"
    echo ""
    read -p "Press Enter after adding peer on VPS..."

    # Client config — SPLIT TUNNEL: only CloudCode traffic
    # We route only the specific Google IPs through the tunnel
    cat > /etc/wireguard/agy.conf << EOF
[Interface]
PrivateKey = $CLIENT_PRIV
Address = 10.8.0.2/32
DNS = 8.8.8.8

[Peer]
PublicKey = $(ssh -o StrictHostKeyChecking=no root@$VPS_IP "cat /etc/wireguard/server_public.key" 2>/dev/null || echo "SERVER_PUBLIC_KEY")
Endpoint = $VPS_IP:51820
# Split tunnel: only route CloudCode IPs through tunnel
# These are Google's IPs for cloudcode-pa and generativelanguage
AllowedIPs = 172.217.0.0/16, 172.216.0.0/16, 173.194.0.0/16, 142.250.0.0/15
PersistentKeepalive = 25
EOF

    # Start WireGuard client
    systemctl enable wg-quick@agy
    systemctl start wg-quick@agy

    echo ""
    echo "=== WireGuard client configured (split-tunnel) ==="
    echo ""
    echo "Verifying tunnel..."
    sleep 3

    # Check if tunnel works for CloudCode
    echo "Testing CloudCode connectivity through tunnel..."
    timeout 10 curl -sI "https://daily-cloudcode-pa.googleapis.com/" 2>&1 | head -3

    echo ""
    echo "Testing agy..."
    timeout 20 /home/nwk/.local/bin/agy -p "respond with just: wireguard ok" --output-format json 2>/dev/null | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
status = d.get('status', '?')
resp = d.get('response', 'none')[:80]
print(f'  Status: {status}')
print(f'  Response: {resp}')
if status == 'SUCCESS':
    print('  ✅ TEST #3 PASSED!')
else:
    print('  ❌ TEST #3 FAILED')
" 2>/dev/null || echo "  ❌ Timeout/Error"

    echo ""
    echo "=== Management: ==="
    echo "  Start:   sudo systemctl start wg-quick@agy"
    echo "  Stop:    sudo systemctl stop wg-quick@agy"
    echo "  Status:  sudo wg show"
    echo "  Cleanup: sudo systemctl disable wg-quick@agy && sudo rm /etc/wireguard/agy.conf"

    exit 0
fi
