import asyncio
import websockets
import json

clients = set()

async def handler(ws):
    # Add new client
    clients.add(ws)
    print("Client connected")
    try:
        async for msg in ws:
            print("Received from client (optional):", msg)
    finally:
        clients.remove(ws)
        print("Client disconnected")

async def broadcast(data):
    if clients:
        message = json.dumps(data)
        await asyncio.wait([client.send(message) for client in clients])

async def main():
    # Run WebSocket server
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("WebSocket server running on port 8080")

        # Example: periodically send messages (simulate Python fetcher)
        counter = 0
        while True:
            example_data = {"job_ids": [f"job-{counter}", f"job-{counter+1}"]}
            await broadcast(example_data)
            counter += 2
            await asyncio.sleep(10)

asyncio.run(main())
