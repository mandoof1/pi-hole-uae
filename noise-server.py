#!/usr/bin/env python3
"""
Noise Injector — Control Server v2
Serves noise injector web UI + API. Manages Pi-hole allow-list
lifecycle so tracking domains pass through during injection.
Mixes tracking domains + real popular domains for realistic noise.
"""

import http.server
import json
import subprocess
import os
import signal
import time
import re
import random
import threading

PORT = 8081
SCRIPT = "/opt/pihole/noise-injector.sh"
TRACKING_LIST = "/tmp/noise-tracking.txt"
REAL_LIST = "/tmp/noise-real.txt"
ALLOW_LOG = "/tmp/noise-allow-ids.txt"
INJECTOR_PROCESS = None
START_TIME = None
TOTAL_SENT = 0
BURSTS = 0
LOCK = threading.Lock()

REAL_DOMAINS = [
    "google.com", "youtube.com", "facebook.com", "instagram.com", "whatsapp.com",
    "tiktok.com", "snapchat.com", "x.com", "twitter.com", "linkedin.com",
    "reddit.com", "pinterest.com", "netflix.com", "amazon.com", "ebay.com",
    "wikipedia.org", "imdb.com", "stackoverflow.com", "github.com", "gitlab.com",
    "apple.com", "microsoft.com", "zoom.us", "spotify.com", "telegram.org",
    "cnn.com", "bbc.com", "nytimes.com", "theguardian.com", "aljazeera.com",
    "gulfnews.com", "khaleejtimes.com", "thenationalnews.com", "arabnews.com",
    "dubizzle.com", "bayut.com", "propertyfinder.ae", "amazon.ae", "noon.com",
    "talabat.com", "careem.com", "uber.com", "booking.com", "airbnb.com",
    "paypal.com", "stripe.com", "visa.com", "mastercard.com",
    "dropbox.com", "onedrive.com", "icloud.com", "drive.google.com", "office.com",
    "speedtest.net", "cloudflare.com", "namecheap.com", "godaddy.com", "verisign.com",
    "aliexpress.com", "alibaba.com", "walmart.com", "bestbuy.com", "target.com",
    "npmjs.com", "pypi.org", "docker.com", "kubernetes.io", "python.org",
    "stackexchange.com", "medium.com", "quora.com", "wordpress.com", "blogger.com",
    "weather.com", "accuweather.com", "timeanddate.com", "cricket.com", "espn.com",
]


PIHOLE_AUTH = None

def pihole_auth():
    global PIHOLE_AUTH
    if PIHOLE_AUTH is not None:
        return PIHOLE_AUTH
    try:
        auth = subprocess.check_output(
            ["curl", "-s", "-X", "POST", "http://localhost/api/auth",
             "-H", "Content-Type: application/json", "-d", '{"password":"meow"}'])
        d = json.loads(auth)
        PIHOLE_AUTH = (d["session"]["sid"], d["session"]["csrf"])
        return PIHOLE_AUTH
    except Exception as e:
        return None

def pihole_api(method, path, data=None):
    try:
        a = pihole_auth()
        if not a:
            return {"error": "auth failed"}
        sid, csrf = a
        h = ["-H", "X-FTL-SID:" + sid, "-H", "X-FTL-CSRF:" + csrf,
             "-H", "Content-Type: application/json"]
        if method == "GET":
            return json.loads(subprocess.check_output(["curl", "-s", "http://localhost/api" + path] + h))
        elif method == "POST":
            return json.loads(subprocess.check_output(
                ["curl", "-s", "-X", "POST", "http://localhost/api" + path] + h + ["-d", data]))
        elif method == "DELETE":
            return json.loads(subprocess.check_output(
                ["curl", "-s", "-X", "DELETE", "http://localhost/api" + path] + h))
    except Exception as e:
        return {"error": str(e)}


def load_tracking_domains(limit=300):
    domains = []
    try:
        result = subprocess.check_output(
            ["sudo", "sqlite3", "/etc/pihole/gravity.db",
             "SELECT domain FROM gravity ORDER BY RANDOM() LIMIT {};".format(limit)])
        domains = [d.decode().strip() for d in result.splitlines() if d.strip()]
    except:
        pass
    return domains


def temp_allow_domains(domains):
    ids = []
    for d in domains[:100]:
        resp = pihole_api("POST", "/lists?type=allow",
                          json.dumps({"address": d, "comment": "noise-injector-temp"}))
        if "lists" in resp:
            for lst in resp["lists"]:
                ids.append(lst.get("id"))
        time.sleep(0.02)
    with open(ALLOW_LOG, "w") as f:
        f.write("\n".join(str(i) for i in ids))
    return ids


def remove_temp_allows():
    if not os.path.exists(ALLOW_LOG):
        return 0
    count = 0
    with open(ALLOW_LOG) as f:
        for line in f:
            lid = line.strip()
            if lid:
                pihole_api("DELETE", "/lists/{}?type=allow".format(lid))
                count += 1
                time.sleep(0.02)
    try:
        os.remove(ALLOW_LOG)
    except:
        pass
    return count


def write_domain_files(tracking, real):
    with open(TRACKING_LIST, "w") as f:
        for d in tracking:
            f.write(d + "\n")
    with open(REAL_LIST, "w") as f:
        for d in real:
            f.write(d + "\n")


def get_log_stats():
    try:
        with open("/var/log/noise-injector.log") as f:
            content = f.read()
            total = 0
            bursts = 0
            for m in re.findall(r'total:\s*(\d+)', content):
                total = int(m)
            for m in re.findall(r'Burst #(\d+)', content):
                bursts = int(m)
            return total, bursts
    except:
        return TOTAL_SENT, BURSTS


def read_status():
    global TOTAL_SENT, BURSTS
    data = {"status": "idle", "total_sent": TOTAL_SENT, "bursts": BURSTS, "elapsed": 0}
    with LOCK:
        running = INJECTOR_PROCESS and INJECTOR_PROCESS.poll() is None
        if running:
            data["status"] = "active"
            if START_TIME:
                data["elapsed"] = int(time.time() - START_TIME)
            data["total_sent"] = TOTAL_SENT
            data["bursts"] = BURSTS
    t, b = get_log_stats()
    if t > data["total_sent"]:
        data["total_sent"] = t
    if b > data["bursts"]:
        data["bursts"] = b
    return data


def _start_worker():
    global INJECTOR_PROCESS, START_TIME, TOTAL_SENT, BURSTS
    try:
        tracking = load_tracking_domains(300)
        if not tracking:
            print("ERROR: Could not load tracking domains")
            return
        allowed = temp_allow_domains(tracking)
        print("Allowed {} tracking domains through Pi-hole".format(len(allowed)))
        real = random.sample(REAL_DOMAINS, min(100, len(REAL_DOMAINS)))
        write_domain_files(tracking, real)
        try:
            open("/var/log/noise-injector.log", "w").close()
        except:
            pass
        with LOCK:
            START_TIME = time.time()
            TOTAL_SENT = 0
            BURSTS = 0
            INJECTOR_PROCESS = subprocess.Popen(
                ["sudo", SCRIPT, TRACKING_LIST, REAL_LIST],
                stdout=open("/var/log/noise-injector.log", "a"),
                stderr=subprocess.STDOUT
            )
    except Exception as e:
        print("ERROR starting injector: " + str(e))


def start_injector():
    with LOCK:
        if INJECTOR_PROCESS and INJECTOR_PROCESS.poll() is None:
            return {"status": "error", "message": "Already running"}
    t = threading.Thread(target=_start_worker, daemon=True)
    t.start()
    time.sleep(0.5)
    return {"status": "started", "message": "Injector arming..."}


def _stop_worker():
    global INJECTOR_PROCESS, TOTAL_SENT, BURSTS, START_TIME
    t, b = get_log_stats()
    with LOCK:
        TOTAL_SENT = max(TOTAL_SENT, t)
        BURSTS = max(BURSTS, b)
    try:
        with open("/var/run/noise-injector.stop", "w") as f:
            f.write("1")
    except:
        pass
    with LOCK:
        if INJECTOR_PROCESS:
            try:
                INJECTOR_PROCESS.terminate()
                INJECTOR_PROCESS.wait(timeout=5)
            except:
                try: INJECTOR_PROCESS.kill()
                except: pass
            INJECTOR_PROCESS = None
        START_TIME = None
    removed = remove_temp_allows()
    for f in [TRACKING_LIST, REAL_LIST, "/var/run/noise-injector.pid",
              "/var/run/noise-injector.stop"]:
        try: os.remove(f)
        except: pass
    try:
        subprocess.Popen(["sudo", "pihole", "-g"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass
    print("Stopped. {} allow entries removed. Gravity updating.".format(removed))


def stop_injector():
    with LOCK:
        if not INJECTOR_PROCESS or INJECTOR_PROCESS.poll() is not None:
            return {"status": "idle", "message": "Not running"}
    t = threading.Thread(target=_stop_worker, daemon=True)
    t.start()
    return {"status": "stopping", "message": "Stopping injector and re-blocking domains..."}


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Noise Injector — Pi-hole</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; }
  .container { max-width: 500px; width: 90%; text-align: center; padding: 2rem; }
  h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.5rem; }
  .subtitle { color: #888; font-size: 0.85rem; margin-bottom: 0.5rem; line-height: 1.4; }
  .note { color: #666; font-size: 0.75rem; margin-bottom: 2rem; font-style: italic; }
  .status-card { background: #16213e; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; border: 1px solid #0f3460; }
  .status-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: 0.5rem; }
  .status-value { font-size: 1.1rem; font-weight: 500; }
  .status-value.idle { color: #4ade80; }
  .status-value.poisoning { color: #fbbf24; animation: blink 1s ease-in-out infinite; }
  @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
  #poison-btn { width: 180px; height: 180px; border-radius: 50%; border: none; font-size: 1.3rem; font-weight: 700; cursor: pointer; transition: all 0.3s ease; text-transform: uppercase; letter-spacing: 2px; margin: 1.5rem auto; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
  #poison-btn.idle { background: linear-gradient(135deg, #1a1a2e, #16213e); color: #4ade80; border: 3px solid #4ade80; }
  #poison-btn.idle:hover { background: linear-gradient(135deg, #16213e, #0f3460); box-shadow: 0 4px 30px rgba(74,222,128,0.2); transform: scale(1.05); }
  #poison-btn.poisoning { background: linear-gradient(135deg, #7f1d1d, #991b1b); color: #fbbf24; border: 3px solid #fbbf24; animation: pulse 1.5s ease-in-out infinite; }
  #poison-btn.poisoning:hover { background: linear-gradient(135deg, #991b1b, #b91c1c); }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 20px rgba(251,191,36,0.3); } 50% { box-shadow: 0 0 40px rgba(251,191,36,0.6); } }
  .stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; margin-top: 1.5rem; }
  .stat-box { background: #16213e; border-radius: 8px; padding: 0.75rem; border: 1px solid #0f3460; }
  .stat-num { font-size: 1.4rem; font-weight: 700; color: #e0e0e0; }
  .stat-desc { font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 0.25rem; }
  .log { background: #0d1b2a; border-radius: 8px; padding: 1rem; margin-top: 1.5rem; text-align: left; font-family: 'Courier New', monospace; font-size: 0.75rem; color: #666; max-height: 200px; overflow-y: auto; border: 1px solid #0f3460; }
  .log-entry { margin: 0.2rem 0; }
  .nav-link { margin-top: 2rem; font-size: 0.85rem; }
  .nav-link a { color: #4ade80; text-decoration: none; }
  .nav-link a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <h1>☠️ Noise Injector</h1>
  <p class="subtitle">Floods tracking domains with fake DNS queries from randomized IPs.<br>Tracking domains are temporarily unblocked so noise reaches upstream.</p>
  <p class="note">Mix of tracking domains + real traffic (Google, YouTube, Amazon, etc.)</p>
  <div class="status-card">
    <div class="status-label">Status</div>
    <div class="status-value idle" id="status-text">● IDLE</div>
  </div>
  <button id="poison-btn" class="idle" onclick="toggle()">ARM</button>
  <div class="stats">
    <div class="stat-box"><div class="stat-num" id="queries-sent">0</div><div class="stat-desc">Sent</div></div>
    <div class="stat-box"><div class="stat-num" id="bursts">0</div><div class="stat-desc">Bursts</div></div>
    <div class="stat-box"><div class="stat-num" id="duration">0s</div><div class="stat-desc">Running</div></div>
  </div>
  <div class="log" id="log"><div class="log-entry">[Ready] Click ARM to start poisoning their data.</div></div>
  <div class="nav-link"><a href="/admin/" target="_parent">← Back to Pi-hole Admin</a></div>
</div>
<script>
let active = false; let pollInterval = null;
function log(m) { const e=document.getElementById('log'); const d=document.createElement('div'); d.className='log-entry'; d.textContent='['+new Date().toLocaleTimeString()+'] '+m; e.appendChild(d); e.scrollTop=e.scrollHeight; }
function upd(state,data) {
  const se=document.getElementById('status-text'), btn=document.getElementById('poison-btn');
  const qe=document.getElementById('queries-sent'), be=document.getElementById('bursts'), de=document.getElementById('duration');
  if(state==='idle') {
    active=false; se.textContent='● IDLE'; se.className='status-value idle';
    btn.textContent='ARM'; btn.className='idle';
    if(pollInterval){clearInterval(pollInterval);pollInterval=null;}
    if(data){qe.textContent=data.total_sent||0;be.textContent=data.bursts||0;de.textContent=(data.elapsed||0)+'s';}
  } else if(state==='active') {
    active=true; se.textContent='☠️ POISONING'; se.className='status-value poisoning';
    btn.textContent='DISARM'; btn.className='poisoning';
    qe.textContent=data?.total_sent||0; be.textContent=data?.bursts||0; de.textContent=(data?.elapsed||0)+'s';
  }
}
function toggle() {
  fetch((active?'/stop':'/start')).then(r=>r.json()).then(data=>{
    if(data.status==='started'){upd('active',data);if(!pollInterval)pollInterval=setInterval(pollStatus,2000);log('Arming... unblocking tracking domains.');}
    else if(data.status==='stopping'){log('Disarming... re-blocking domains.');setTimeout(pollStatus,3000);}
    else if(data.status==='idle'){upd('idle',data);if(pollInterval){clearInterval(pollInterval);pollInterval=null;}}
    else log('Error: '+(data.message||'unknown'));
  }).catch(e=>log('Error: '+e.message));
}
function pollStatus() {
  fetch('/status').then(r=>r.json()).then(data=>{
    if(data.status==='active')upd('active',data);
    else if(data.status==='stopping'){se.textContent='STOPPING...';}
    else upd('idle',data);
  }).catch(()=>{});
}
fetch('/status').then(r=>r.json()).then(data=>{if(data.status==='active'){upd('active',data);pollInterval=setInterval(pollStatus,2000);}}).catch(()=>{});
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        self.send_response(200)
        if path == "/":
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())
        else:
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if path == "/status":
                self.wfile.write(json.dumps(read_status()).encode())
            elif path == "/start":
                self.wfile.write(json.dumps(start_injector()).encode())
            elif path == "/stop":
                self.wfile.write(json.dumps(stop_injector()).encode())
            else:
                self.wfile.write(json.dumps({"status": "error", "message": "Not found"}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print("Noise Injector v2 — http://0.0.0.0:{}".format(PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _stop_worker()
        print("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
