#!/usr/bin/env python3
"""
Noise Injector — Control Server
Serves the noise injector web UI + start/stop/status API.
Designed to run alongside Pi-hole's web server on a separate port.
"""

import http.server
import json
import subprocess
import os
import signal
import time
import re

PORT = 8081
PID_FILE = "/var/run/noise-injector.pid"
SCRIPT = "/opt/pihole/noise-injector.sh"
INJECTOR_PROCESS = None
START_TIME = None
TOTAL_SENT = 0
BURSTS = 0

# Embedded HTML page
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Noise Injector — Pi-hole</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e; color: #e0e0e0;
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
  }
  .container { max-width: 500px; width: 90%; text-align: center; padding: 2rem; }
  h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.5rem; }
  .subtitle { color: #888; font-size: 0.9rem; margin-bottom: 2rem; line-height: 1.4; }
  .status-card {
    background: #16213e; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem;
    border: 1px solid #0f3460;
  }
  .status-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: 0.5rem; }
  .status-value { font-size: 1.1rem; font-weight: 500; }
  .status-value.idle { color: #4ade80; }
  .status-value.poisoning { color: #fbbf24; animation: blink 1s ease-in-out infinite; }
  @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
  #poison-btn {
    width: 180px; height: 180px; border-radius: 50%; border: none;
    font-size: 1.3rem; font-weight: 700; cursor: pointer;
    transition: all 0.3s ease; text-transform: uppercase; letter-spacing: 2px;
    margin: 1.5rem auto; display: flex; align-items: center; justify-content: center;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }
  #poison-btn.idle {
    background: linear-gradient(135deg, #1a1a2e, #16213e); color: #4ade80;
    border: 3px solid #4ade80;
  }
  #poison-btn.idle:hover {
    background: linear-gradient(135deg, #16213e, #0f3460);
    box-shadow: 0 4px 30px rgba(74,222,128,0.2); transform: scale(1.05);
  }
  #poison-btn.poisoning {
    background: linear-gradient(135deg, #7f1d1d, #991b1b); color: #fbbf24;
    border: 3px solid #fbbf24; animation: pulse 1.5s ease-in-out infinite;
  }
  #poison-btn.poisoning:hover { background: linear-gradient(135deg, #991b1b, #b91c1c); }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 20px rgba(251,191,36,0.3); } 50% { box-shadow: 0 0 40px rgba(251,191,36,0.6); } }
  .stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; margin-top: 1.5rem; }
  .stat-box { background: #16213e; border-radius: 8px; padding: 0.75rem; border: 1px solid #0f3460; }
  .stat-num { font-size: 1.4rem; font-weight: 700; color: #e0e0e0; }
  .stat-desc { font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 0.25rem; }
  .log {
    background: #0d1b2a; border-radius: 8px; padding: 1rem; margin-top: 1.5rem;
    text-align: left; font-family: 'Courier New', monospace;
    font-size: 0.75rem; color: #666; max-height: 200px; overflow-y: auto;
    border: 1px solid #0f3460;
  }
  .log-entry { margin: 0.2rem 0; }
  .nav-link { margin-top: 2rem; font-size: 0.85rem; }
  .nav-link a { color: #4ade80; text-decoration: none; }
  .nav-link a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <h1>☠️ Noise Injector</h1>
  <p class="subtitle">Floods tracking domains with fake DNS queries<br>from randomized IPs to poison their analytics</p>
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
  <div class="log" id="log"><div class="log-entry">[Ready] Injector idle. Click ARM to start.</div></div>
  <div class="nav-link"><a href="http://YOUR_PI_IP/admin/" target="_parent">← Back to Pi-hole Admin</a></div>
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
    log('Injector stopped. Total: '+(data?.total_sent||0)+' queries');
  } else if(state==='active') {
    active=true; se.textContent='☠️ POISONING'; se.className='status-value poisoning';
    btn.textContent='DISARM'; btn.className='poisoning';
    qe.textContent=data?.total_sent||0; be.textContent=data?.bursts||0; de.textContent=(data?.elapsed||0)+'s';
  }
}
function toggle() {
  fetch((active?'/stop':'/start')).then(r=>r.json()).then(data=>{
    if(data.status==='started'){upd('active',data);if(!pollInterval)pollInterval=setInterval(pollStatus,2000);log('Injector armed.');}
    else if(data.status==='stopped'){upd('idle',data);log('Injector disarmed.');}
    else log('Error: '+(data.message||'unknown'));
  }).catch(e=>log('Error: '+e.message));
}
function pollStatus() {
  fetch('/status').then(r=>r.json()).then(data=>{
    if(data.status==='active')upd('active',data);else upd('idle',data);
  }).catch(()=>{});
}
fetch('/status').then(r=>r.json()).then(data=>{if(data.status==='active'){upd('active',data);pollInterval=setInterval(pollStatus,2000);}}).catch(()=>{});
</script>
</body>
</html>"""


def read_status():
    data = {"status": "idle", "total_sent": 0, "bursts": 0, "elapsed": 0}
    if INJECTOR_PROCESS and INJECTOR_PROCESS.poll() is None:
        data["status"] = "active"
        if START_TIME:
            data["elapsed"] = int(time.time() - START_TIME)
        data["total_sent"] = TOTAL_SENT
        data["bursts"] = BURSTS
    try:
        with open("/var/log/noise-injector.log") as f:
            content = f.read()
            m = re.findall(r'total:\s*(\d+)', content)
            if m:
                data["total_sent"] = max(data["total_sent"], int(m[-1]))
            m = re.findall(r'Burst #(\d+)', content)
            if m:
                data["bursts"] = sum(int(x) for x in m[-10:])
    except:
        pass
    return data


def start_injector():
    global INJECTOR_PROCESS, START_TIME, TOTAL_SENT, BURSTS
    if INJECTOR_PROCESS and INJECTOR_PROCESS.poll() is None:
        return {"status": "error", "message": "Already running"}
    START_TIME = time.time()
    TOTAL_SENT = 0
    BURSTS = 0
    try:
        INJECTOR_PROCESS = subprocess.Popen(
            ["sudo", SCRIPT],
            stdout=open("/var/log/noise-injector.log", "a"),
            stderr=subprocess.STDOUT
        )
        time.sleep(0.3)
        return {"status": "started", "message": "Injector launched"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def stop_injector():
    global INJECTOR_PROCESS, TOTAL_SENT, BURSTS, START_TIME
    data = read_status()
    TOTAL_SENT = data.get("total_sent", TOTAL_SENT)
    BURSTS = data.get("bursts", BURSTS)
    try:
        with open("/var/run/noise-injector.stop", "w") as f:
            f.write("1")
    except:
        pass
    if INJECTOR_PROCESS:
        try:
            INJECTOR_PROCESS.terminate()
            INJECTOR_PROCESS.wait(timeout=5)
        except:
            try: INJECTOR_PROCESS.kill()
            except: pass
        INJECTOR_PROCESS = None
    elapsed = int(time.time() - START_TIME) if START_TIME else 0
    START_TIME = None
    for f in ["/var/run/noise-injector.pid", "/var/run/noise-injector.stop"]:
        try: os.remove(f)
        except: pass
    return {"status": "stopped", "total_sent": TOTAL_SENT, "bursts": BURSTS, "elapsed": elapsed}


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
    print("Noise Injector — http://0.0.0.0:{}".format(PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_injector()
        print("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
