# Pi-hole on UAE Networks — Local Ad Blocklist & Setup Guide

A complete guide to setting up **Pi-hole** on UAE home/office networks, including a **curated blocklist of UAE-specific ad domains, trackers, and telemetry servers** that general-purpose blocklists often miss.

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

- A **Raspberry Pi** (3B+ or newer, 4GB+ RAM recommended)
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

> **Note:** The `--unattended` flag skips interactive dialogs. You may need to set a **static IP** on your Pi first using your network manager (e.g., `nmcli` on Raspberry Pi OS).

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

Copy the `uae-blocklist.txt` file to your Pi, then add it:

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
├── README.md            # This guide
├── uae-blocklist.txt    # UAE-specific ad/tracker domains
├── LICENSE
```

---

## Contributing

Found a UAE ad domain that's slipping through? Open a PR or issue with the domain and a note on where it was found. The list is most effective when the community keeps it current.

---

## License

MIT — free to use, modify, and share. No affiliation with Pi-hole or any listed entity.
