import asyncio
import requests
import websockets
import json
import time

# ---------------------------
# Configuration
# ---------------------------
BASE_URL = "https://games.roblox.com/v1/games/109983668079237/servers/Public"
LIMIT = 100
ROTATE_DELAY = 5     # Reduced for faster testing
BACKOFF = 60
TIMEOUT = 15

PROXIES_RAW = [
    "31.59.20.176:6754:tphrhwdj:my6aw2vrkipo",
    "23.95.150.145:6114:tphrhwdj:my6aw2vrkipo",
    "198.23.239.134:6540:tphrhwdj:my6aw2vrkipo",
    "45.38.107.97:6014:tphrhwdj:my6aw2vrkipo",
    "107.172.163.27:6543:tphrhwdj:my6aw2vrkipo",
    "198.105.121.200:6462:tphrhwdj:my6aw2vrkipo",
    "64.137.96.74:6641:tphrhwdj:my6aw2vrkipo",
    "216.10.27.159:6837:tphrhwdj:my6aw2vrkipo",
    "23.26.71.145:5628:tphrhwdj:my6aw2vrkipo",
    "23.229.19.94:8689:tphrhwdj:my6aw2vrkipo"
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close"
}

# ---------------------------
# Helpers
# ---------------------------
def format_proxy(p):
    ip, port, user, pwd = p.split(":")
    proxy = f"http://{user}:{pwd}@{ip}:{port}"
    return {"http": proxy, "https": proxy}

# ---------------------------
# WebSocket Server
# ---------------------------
clients = set()
job_ids_available = set()
job_ids_blocked = {}  # job_id -> unblock timestamp (epoch)

async def broadcast(data):
    if clients:
        message = json.dumps(data)
        await asyncio.gather(*[asyncio.create_task(client.send(message)) for client in clients])

async def handle_request_job(ws):
    now = time.time()
    # Remove expired blocked JobIds
    expired = [jid for jid, ts in job_ids_blocked.items() if ts <= now]
    for jid in expired:
        job_ids_blocked.pop(jid)

    if not job_ids_available:
        print("No JobIds available for client")
        await ws.send(json.dumps({"error": "No JobIds available"}))
        return

    job_id = job_ids_available.pop()
    job_ids_blocked[job_id] = now + 600  # block for 10 minutes
    await ws.send(json.dumps({"job_id": job_id}))
    print(f"Sent JobId {job_id} to client, blocked for 10 minutes")

async def ws_handler(ws):
    clients.add(ws)
    print("Client connected")

    # Send current JobIds immediately on connect
    if job_ids_available:
        await ws.send(json.dumps({"job_ids": list(job_ids_available)}))

    try:
        while True:
            try:
                msg = await ws.recv()
            except websockets.exceptions.ProtocolError as e:
                print("Protocol error (likely Roblox masking):", e)
                break
            except websockets.exceptions.ConnectionClosed:
                print("Client disconnected")
                break

            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"error": "Invalid JSON"}))
                continue

            if data.get("action") == "request_job":
                await handle_request_job(ws)
            else:
                await ws.send(json.dumps({"error": "Unknown action"}))

    finally:
        clients.remove(ws)
        print("Client disconnected")

# ---------------------------
# Fetch JobIds from Roblox API
# ---------------------------
async def fetch_job_ids():
    proxy_index = 0
    next_cursor = None
    dead_proxies = set()

    while True:
        raw_proxy = PROXIES_RAW[proxy_index]
        if raw_proxy in dead_proxies:
            proxy_index = (proxy_index + 1) % len(PROXIES_RAW)
            continue

        proxies = format_proxy(raw_proxy)
        params = {"limit": LIMIT}
        if next_cursor:
            params["cursor"] = next_cursor

        try:
            r = requests.get(BASE_URL, headers=headers, proxies=proxies, params=params, timeout=TIMEOUT)

            if r.status_code == 200:
                j = r.json()
                servers = j.get("data", [])
                next_cursor = j.get("nextPageCursor")

                # Add JobIds if not already available or blocked
                new_job_ids = [s["id"] for s in servers
                               if s["id"] not in job_ids_available
                               and s["id"] not in job_ids_blocked]

                if new_job_ids:
                    job_ids_available.update(new_job_ids)
                    print(f"Added JobIds: {new_job_ids}")
                    await broadcast({"job_ids": list(job_ids_available)})

                if not next_cursor:
                    next_cursor = None
                sleep = ROTATE_DELAY

            elif r.status_code == 429:
                print("Rate limited, backing off...")
                sleep = BACKOFF
            else:
                print("HTTP error:", r.status_code)
                sleep = BACKOFF

        except requests.exceptions.SSLError:
            print("TLS failed — proxy is dead")
            dead_proxies.add(raw_proxy)
            sleep = 5
        except requests.RequestException as e:
            print("Request failed:", e)
            sleep = BACKOFF

        proxy_index = (proxy_index + 1) % len(PROXIES_RAW)
        await asyncio.sleep(sleep)

# ---------------------------
# Main Async Runner
# ---------------------------
async def main():
    server = await websockets.serve(ws_handler, "0.0.0.0", 8080)
    print("WebSocket server running on port 8080")
    await asyncio.gather(fetch_job_ids(), server.wait_closed())

if __name__ == "__main__":
    asyncio.run(main())
