#!/bin/bash
# Noise Injector — Pi-hole Analytics Poisoner
# Creates virtual IPs on the interface and fires DNS queries from each
# to flood tracking domains with garbage traffic.
#
# Configuration — edit these to tune performance
INTERFACE="wlan0"
FAKE_SUBNET="192.168.x"
DOMAIN_COUNT=500
BURST_SIZE=30
MAX_FAKE_IPS=20
SLEEP_SECS=0.3
PID_FILE="/var/run/noise-injector.pid"
STOP_FILE="/var/run/noise-injector.stop"

cleanup() {
    echo "[*] Cleaning up fake IPs..."
    for ((i=2; i<=MAX_FAKE_IPS+1; i++)); do
        sudo ip addr del ${FAKE_SUBNET}.$i/24 dev $INTERFACE 2>/dev/null
    done
    rm -f "$PID_FILE" "$STOP_FILE" 2>/dev/null
    echo "[*] Cleanup complete."
}

trap cleanup EXIT INT TERM

# Check if already running
if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        echo "[!] Already running (PID $old_pid)."
        exit 1
    fi
    rm -f "$PID_FILE"
fi

echo "$$" > "$PID_FILE"
rm -f "$STOP_FILE"

# Add fake IPs
echo "[*] Adding $MAX_FAKE_IPS fake IPs to $INTERFACE..."
for ((i=2; i<=MAX_FAKE_IPS+1; i++)); do
    sudo ip addr add ${FAKE_SUBNET}.$i/24 dev $INTERFACE 2>/dev/null
done

# Load domains from Pi-hole gravity database
DOMAINS_FILE=$(mktemp)
sudo sqlite3 /etc/pihole/gravity.db "SELECT domain FROM gravity ORDER BY RANDOM() LIMIT $DOMAIN_COUNT;" > "$DOMAINS_FILE" 2>/dev/null

# Fallback if gravity database is unavailable
if [ ! -s "$DOMAINS_FILE" ]; then
    cat > "$DOMAINS_FILE" << 'ENDDOMAINS'
doubleclick.net
googleadservices.com
googlesyndication.com
google-analytics.com
googletagmanager.com
adsrvr.org
adnxs.com
rubiconproject.com
criteo.com
pubmatic.com
openx.net
casalemedia.com
moatads.com
adsafeprotected.com
scorecardresearch.com
quantserve.com
exponential.com
tribalfusion.com
turn.com
adhigh.net
ENDDOMAINS
fi

mapfile -t DOMAINS < "$DOMAINS_FILE"
rm -f "$DOMAINS_FILE"
echo "[*] Loaded ${#DOMAINS[@]} domains"
echo "[*] Running until stop signal received..."

TOTAL=0
BURST_NUM=0

while true; do
    if [ -f "$STOP_FILE" ]; then
        echo "[!] Stop signal received."
        break
    fi

    FAKE_IP_IDX=$(( (BURST_NUM % MAX_FAKE_IPS) + 2 ))
    SRC_IP="${FAKE_SUBNET}.${FAKE_IP_IDX}"
    ((BURST_NUM++))

    COUNT=0
    for DOMAIN in "${DOMAINS[@]}"; do
        dig +short @127.0.0.1 -b "$SRC_IP" "$DOMAIN" A >/dev/null 2>&1 &
        ((COUNT++))
        [ $COUNT -ge $BURST_SIZE ] && break
    done

    TOTAL=$((TOTAL + COUNT))
    echo "[$(date +%H:%M:%S)] Burst #$BURST_NUM — $COUNT queries from $SRC_IP (total: $TOTAL)"

    wait 2>/dev/null
    sleep "$SLEEP_SECS"
done

echo "[*] Done. $TOTAL total queries injected."
