# Pi-hole on UAE Networks — Local Ad Blocklist & Setup Guide

A complete guide to setting up **Pi-hole** on UAE home/office networks, including a **curated blocklist of UAE-specific ad domains, trackers, and telemetry servers** that general-purpose blocklists often miss, plus a **Noise Injector** — a big red button that floods tracking domains with garbage DNS traffic to poison their analytics.

---

## Why This Exists

Global blocklists like StevenBlack and OISD cover the big players (Google, Facebook, etc.), but **local UAE ad networks, telecom trackers (Etisalat/du), and regional ad exchanges** frequently slip through. This repo fills that gap.

**The UAE blocklist targets:**
- UAE telecom ad servers & analytics (Etisalat, du)
- Regional ad exchanges & networks (Adhigh, Adman, Mnet)
- UAE news & media ad infrastructure (Gulf News, Khaleej Times, The National, Al Khaleej, Al Bayan, Emirates Al Youm)
- UAE classifieds & e-commerce trackers (Dubizzle, Bayut, Property Finder, OpenSooq)
- UAE business & jobs portals (Zawya, Arabian Business, GulfTalent)
- ITP & Motory media network trackers
- General UAE web trackers & analytics pixels

**Combined with the recommended base lists, you block 430,000+ domains — covering global + local threats.**

---

## Prerequisites

- A **Raspberry Pi** (3B+ or newer, 2GB+ RAM recommended)
- **Raspberry Pi OS Lite** (64-bit) or similar Debian-based distro
- Network access to your router's admin panel
- Basic familiarity with the terminal

---

## Quick Setup

### 1. Install Pi-hole

SSH into your Pi and run:

```bash
# Download the installer
wget -O /tmp/pihole-install.sh https://install.pi-hole.net
chmod +x /tmp/pihole-install.sh

# Run unattended install (customize interface/DNS as needed)
sudo PIHOLE_INTERFACE=wlan0 \
     PIHOLE_DNS_1=1.1.1.1 \
     PIHOLE_DNS_2=1.0.0.1 \
     PIHOLE_WEBPASSWORD="your-admin-password" \
     bash /tmp/pihole-install.sh --unattended
```

> **Note:** The `--unattended` flag skips interactive dialogs. You may need to set a **static IP** on your Pi first using your network manager (e.g., `nmcli` on Raspberry Pi OS). If the installer fails due to a dialog blocking, patch the `fresh_install` block or pre-create `/etc/pihole/` before running.

### 2. Set a Static IP

```bash
# Find your connection name
nmcli con show --active

# Set static IP (adjust for your subnet)
sudo nmcli con mod "your-connection-name" \
     ipv4.method manual \
     ipv4.addresses 192.168.x.58/24 \
     ipv4.gateway 192.168.x.1 \
     ipv4.dns "1.1.1.1 1.0.0.1"

sudo nmcli con down "your-connection-name"
sudo nmcli con up "your-connection-name"
```

### 3. Set the Web Admin Password

```bash
pihole setpassword "your-password"
```

### 4. Add Blocklists

Add the base lists via Pi-hole's API:

```bash
# Authenticate
SESSION=$(curl -s -X POST "http://localhost/api/auth" \
  -H "Content-Type: application/json" \
  -d '{"password":"your-password"}')

SID=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['session']['sid'])")
CSRF=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['session']['csrf'])")

# Add StevenBlack
curl -s -X POST "http://localhost/api/lists?type=block" \
  -H "Content-Type: application/json" \
  -H "X-FTL-SID: $SID" -H "X-FTL-CSRF: $CSRF" \
  -d '{"address":"https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts","comment":"StevenBlack Unified Hosts"}'

# Add OISD
curl -s -X POST "http://localhost/api/lists?type=block" \
  -H "Content-Type: application/json" \
  -H "X-FTL-SID: $SID" -H "X-FTL-CSRF: $CSRF" \
  -d '{"address":"https://big.oisd.nl/","comment":"OISD Full"}'
```

> **Total from these two:** ~432,000+ blocked domains covering global ad networks.

### 5. Add the UAE-Specific Blocklist

Copy the `uae-blocklist.txt` file to your Pi (from this repo), then add it:

```bash
# Copy the file to your Pi
scp uae-blocklist.txt user@your-pi:/etc/pihole/uae-blocklist.txt

# Add it as a local adlist via the API
curl -s -X POST "http://localhost/api/lists?type=block" \
  -H "Content-Type: application/json" \
  -H "X-FTL-SID: $SID" -H "X-FTL-CSRF: $CSRF" \
  -d '{"address":"file:///etc/pihole/uae-blocklist.txt","comment":"UAE-specific ads & trackers"}'
```

### 6. Update Gravity

```bash
pihole -g
```

---

## Network-Wide Coverage (DHCP)

For every device on your network to use Pi-hole automatically:

### On the Router:
1. Log into your router's admin panel (usually `http://192.168.x.1`)
2. Find **DHCP Settings** (usually under Advanced → Network → LAN)
3. **Disable** the router's DHCP server
4. Save

### On Pi-hole:
Enable its built-in DHCP server via the API:

```bash
curl -s -X PATCH "http://localhost/api/config" \
  -H "Content-Type: application/json" \
  -H "X-FTL-SID: $SID" -H "X-FTL-CSRF: $CSRF" \
  -d '{"config":{"dhcp":{"active":true,"start":"192.168.x.2","end":"192.168.x.254","router":"192.168.x.1","netmask":"255.255.255.0","leaseTime":"24","ipv6":false,"rapidCommit":true,"logging":true}}}'
```

Restart FTL: `sudo systemctl restart pihole-FTL`

---

## ☠️ Noise Injector — Poison Their Analytics

A big red button that floods tracking/ad domains with **fake DNS queries from randomized IPs**, making your real traffic invisible in a sea of garbage.

### How It Works

1. When you press **ARM**, the injector creates **20 fake IP addresses** on the Pi's network interface (e.g., `192.168.x.2` through `192.168.x.21`)
2. It loads up to **500 tracking domains** from Pi-hole's gravity database
3. Every cycle, it fires **30 parallel DNS queries** from one of the fake IPs
4. It rotates through all 20 fake IPs, repeating indefinitely
5. Pi-hole logs each query against the corresponding fake IP — the dashboard shows traffic from 20+ "devices"
6. Press **DISARM** to stop

To the outside world, your network appears to have dozens of devices constantly hitting tracking domains. Your genuine DNS queries are buried in the noise.

### Installation

Copy the scripts to your Pi and set up the systemd service:

```bash
# Copy the scripts
sudo cp noise-injector.sh /opt/pihole/noise-injector.sh
sudo cp noise-server.py /opt/pihole/noise-server.py
sudo chmod 755 /opt/pihole/noise-injector.sh /opt/pihole/noise-server.py

# Create the service
sudo tee /etc/systemd/system/noise-injector.service > /dev/null << EOF
[Unit]
Description=Noise Injector API
After=network.target pihole-FTL.service
Requires=pihole-FTL.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/pihole/noise-server.py
Restart=on-failure
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

# Allow the pihole user to run the scripts without password
sudo tee /etc/sudoers.d/noise-injector > /dev/null << EOF
pihole ALL=(ALL) NOPASSWD: /opt/pihole/noise-injector.sh
pihole ALL=(ALL) NOPASSWD: /opt/pihole/noise-server.py
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable noise-injector.service
sudo systemctl start noise-injector.service
```

### Usage

Open `http://your-pi-ip:8081/` in a browser.

- **ARM** (green button) — starts the noise injection
- **DISARM** (yellow pulsing button) — stops it
- Live stats show queries sent, bursts completed, and elapsed time
- The page auto-updates every 2 seconds while active

Auto-starts on boot via systemd.

### Scripts

| File | Description |
|------|-------------|
| `noise-injector.sh` | Bash script that creates fake IPs and fires DNS queries. Runs until `STOP_FILE` signal. |
| `noise-server.py` | Python HTTP server on port 8081. Serves the web UI and handles start/stop/status API calls. |

### Configuration

Edit `/opt/pihole/noise-injector.sh` to tweak:

```bash
DOMAIN_COUNT=500    # Domains to pull from gravity per session
BURST_SIZE=30       # Parallel queries per burst
MAX_FAKE_IPS=20     # Number of fake IPs to create
SLEEP_SECS=0.3      # Delay between bursts (seconds)
```

---

## Verification

```bash
# Test DNS resolution
dig google.com @your-pi-ip

# Test blocking
dig doubleclick.net @your-pi-ip    # Should return 0.0.0.0 or 127.0.0.1

# Check admin panel
# Open http://your-pi-ip/admin/ in a browser
```

---

## Handling Multiple Routers

If you have **secondary routers** connected to the main one:

- **Access Point / Bridge mode** ✅ — They pass through the main router's DHCP, so Pi-hole works automatically for all connected devices.
- **Router / NAT mode** ❌ — They run their own DHCP server. Devices on those subnets won't use Pi-hole unless you either:
  - Manually set each device's DNS to your Pi's IP, or
  - Log into the secondary router and set its DNS server to your Pi's IP

---

## File Structure

```
├── README.md                  # This guide
├── uae-blocklist.txt          # UAE-specific ad/tracker domains
├── noise-injector.sh          # Noise injector backend script
├── noise-server.py            # Web UI + API server
└── LICENSE
```

---

## Contributing

Found a UAE ad domain that's slipping through? Open a PR or issue with the domain and a note on where it was found. The list is most effective when the community keeps it current.

---

## License

MIT — free to use, modify, and share. No affiliation with Pi-hole or any listed entity.
