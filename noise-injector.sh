#!/bin/bash
# Noise Injector — runs until stopped.
# Takes two domain lists: tracking domains + real domains.
# Mixes them together and fires queries from 20 fake IPs.
# Usage: sudo noise-injector.sh <tracking_file> <real_file>

TRACKING_FILE="$1"
REAL_FILE="$2"
INTERFACE="wlan0"
FAKE_SUBNET="192.168.8"
BURST_SIZE=40
MAX_FAKE_IPS=20
SLEEP_SECS=0.25
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

# Load domains
ALL_DOMAINS=()

if [ -n "$TRACKING_FILE" ] && [ -f "$TRACKING_FILE" ]; then
    mapfile -t TRACKING < "$TRACKING_FILE"
    ALL_DOMAINS+=("${TRACKING[@]}")
    echo "[*] Loaded ${#TRACKING[@]} tracking domains"
fi

if [ -n "$REAL_FILE" ] && [ -f "$REAL_FILE" ]; then
    mapfile -t REAL < "$REAL_FILE"
    ALL_DOMAINS+=("${REAL[@]}")
    echo "[*] Loaded ${#REAL[@]} real domains"
fi

echo "[*] Total: ${#ALL_DOMAINS[@]} domains | Running until stop signal..."

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
    for DOMAIN in "${ALL_DOMAINS[@]}"; do
        # Shuffle: pick a random domain from the list each time
        RAND_IDX=$(( RANDOM % ${#ALL_DOMAINS[@]} ))
        dig +short @127.0.0.1 -b "$SRC_IP" "${ALL_DOMAINS[$RAND_IDX]}" A >/dev/null 2>&1 &
        ((COUNT++))
        [ $COUNT -ge $BURST_SIZE ] && break
    done

    TOTAL=$((TOTAL + COUNT))
    echo "[$(date +%H:%M:%S)] Burst #$BURST_NUM — $COUNT queries from $SRC_IP (total: $TOTAL)"

    wait 2>/dev/null
    sleep "$SLEEP_SECS"
done

echo "[*] Done. $TOTAL total queries injected."
