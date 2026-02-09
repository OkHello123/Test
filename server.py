import asyncio
import websockets
import json

clients = set()

async def handler(ws):
    # Keep track of connected clients
    clients.add(ws)
    print("Client connected!")

    try:
        async for msg in ws:
            # Optional: handle messages from Roblox
            print("Received from client:", msg)
            # Example: Echo back to Roblox
            await ws.send(json.dumps({"echo": msg}))
    finally:
        clients.remove(ws)
        print("Client disconnected")

async def broadcast(data):
    if clients:
        message = json.dumps(data)
        # Create tasks explicitly instead of passing raw coroutines
        await asyncio.gather(*[asyncio.create_task(client.send(message)) for client in clients])

async def main():
    # Start WebSocket server
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("WebSocket server running on port 8080")

        counter = 0
        while True:
            # Example message to send to Roblox
            example_data = {
                "job_ids": [f"job-{counter}", f"job-{counter+1}"],
                "note": "This is a test message from the server"
            }
            await broadcast(example_data)
            counter += 2
            await asyncio.sleep(10)  # send every 10 seconds

# Run the server
asyncio.run(main())
