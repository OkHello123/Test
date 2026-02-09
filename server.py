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
ROTATE_DELAY = 5
BACKOFF = 60
TIMEOUT = 15

PROXIES_RAW = [
    "31.59.20.176:6754:tphrhwdj:my6aw2vrkipo",
    "23.95.150.145:6114:tphrhwdj:my6aw2vrkipo",
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
job_ids_queue = asyncio.Queue()
job_ids_blocked = {}  # job_id -> unblock timestamp
blocked_lock = asyncio.Lock()

async def handle_request_job(ws):
    now = time.time()

    # Remove expired blocked JobIds
    async with blocked_lock:
        expired = [jid for jid, ts in job_ids_blocked.items() if ts <= now]
        for jid in expired:
            job_ids_blocked.pop(jid)

    try:
        job_id = job_ids_queue.get_nowait()  # safe for multiple clients
    except asyncio.QueueEmpty:
        await ws.send(json.dumps({"error": "No JobIds available"}))
        return

    # Block the JobId for 10 minutes
    async with blocked_lock:
        job_ids_blocked[job_id] = now + 600

    await ws.send(json.dumps({"job_id": job_id}))
    print(f"Sent JobId {job_id} to client, blocked for 10 minutes")

async def ws_handler(ws):
    clients.add(ws)
    print("Client connected")

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

                # Add new JobIds to queue if not blocked
                async with blocked_lock:
                    for s in servers:
                        job_id = s["id"]
                        if job_id not in job_ids_blocked and job_id not in job_ids_queue._queue:
                            job_ids_queue.put_nowait(job_id)
                            print(f"Added JobId: {job_id}")

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
