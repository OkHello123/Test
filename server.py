import asyncio
import websockets
import json

# Keep track of all connected clients
clients = set()

async def handler(ws):
    clients.add(ws)
    print("Client connected!")
    try:
        async for msg in ws:
            # Optionally handle messages from Roblox
            print("Received from client:", msg)
    finally:
        clients.remove(ws)
        print("Client disconnected")

async def broadcast(data):
    # Send data to all connected clients
    if clients:
        msg = json.dumps(data)
        await asyncio.wait([client.send(msg) for client in clients])

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("WebSocket running on port 8080")

        # Example: simulate messages every 5 seconds
        while True:
            example_data = {"job_ids": ["job1", "job2", "job3"]}
            await broadcast(example_data)
            await asyncio.sleep(5)

asyncio.run(main())
