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
    "198.23.239.134:6540:tphrhwdj:my6aw2vrkipo",
    "45.38.107.97:6014:tphrhwdj:my6aw2vrkipo",
    "107.172.163.27:6543:tphrhwdj:my6aw2vrkipo",
    "198.105.121.200:6462:tphrhwdj:my6aw2vrkipo",
    "64.137.96.74:6641:tphrhwdj:my6aw2vrkipo",
    "216.10.27.159:6837:tphrhwdj:my6aw2vrkipo",
    "23.26.71.145:5628:tphrhwdj:my6aw2vrkipo",
    "23.229.19.94:8689:tphrhwdj:my6aw2vrkipo",
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
job_ids_blocked = {}   # job_id -> unblock timestamp
job_ids_added = {}     # job_id -> timestamp when added
blocked_lock = asyncio.Lock()
queue_lock = asyncio.Lock()

EXPIRATION_SECONDS = 15 * 60  # JobId expires 15 minutes after added
BLOCK_DURATION = 10 * 60      # JobId blocked 10 minutes after assigned

async def handle_request_job(ws):
    now = time.time()

    # Remove expired blocked JobIds
    async with blocked_lock:
        expired_blocked = [jid for jid, ts in job_ids_blocked.items() if ts <= now]
        for jid in expired_blocked:
            job_ids_blocked.pop(jid)

    # Remove expired JobIds from queue
    async with queue_lock:
        expired_queue = [jid for jid, ts in job_ids_added.items() if now - ts >= EXPIRATION_SECONDS]
        for jid in expired_queue:
            try:
                job_ids_queue._queue.remove(jid)
            except ValueError:
                pass
            job_ids_added.pop(jid)
        if expired_queue:
            print(f"Removed expired JobIds from queue: {expired_queue}")

    try:
        async with queue_lock:
            job_id = job_ids_queue.get_nowait()
            job_ids_added.pop(job_id, None)
    except asyncio.QueueEmpty:
        await ws.send(json.dumps({"error": "No JobIds available"}))
        return

    # Block the JobId for 10 minutes
    async with blocked_lock:
        job_ids_blocked[job_id] = now + BLOCK_DURATION

    await ws.send(json.dumps({"job_id": job_id}))
    print(f"Sent JobId {job_id} to client, blocked for {BLOCK_DURATION // 60} minutes")

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

                now = time.time()
                async with blocked_lock, queue_lock:
                    for s in servers:
                        job_id = s["id"]
                        if job_id not in job_ids_blocked and job_id not in job_ids_added:
                            job_ids_queue.put_nowait(job_id)
                            job_ids_added[job_id] = now
                            print(f"Added JobId: {job_id}")

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
# Cleanup Task (Optional)
# ---------------------------
async def cleanup_expired_job_ids():
    """Continuously remove expired JobIds from queue and blocked list"""
    while True:
        now = time.time()

        async with queue_lock:
            expired_queue = [jid for jid, ts in job_ids_added.items() if now - ts >= EXPIRATION_SECONDS]
            for jid in expired_queue:
                try:
                    job_ids_queue._queue.remove(jid)
                except ValueError:
                    pass
                job_ids_added.pop(jid)
            if expired_queue:
                print(f"[Cleanup] Removed expired JobIds: {expired_queue}")

        async with blocked_lock:
            expired_blocked = [jid for jid, ts in job_ids_blocked.items() if ts <= now]
            for jid in expired_blocked:
                job_ids_blocked.pop(jid)

        await asyncio.sleep(10)  # run cleanup every 10 seconds

# ---------------------------
# Main Async Runner
# ---------------------------
async def main():
    server = await websockets.serve(ws_handler, "0.0.0.0", 8080)
    print("WebSocket server running on port 8080")
    await asyncio.gather(
        fetch_job_ids(),
        cleanup_expired_job_ids(),  # ensure queue auto-cleans
        server.wait_closed()
    )

if __name__ == "__main__":
    asyncio.run(main())

