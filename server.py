import asyncio
import json
import websockets

clients = set()

async def handler(ws):
    clients.add(ws)
    print("Client connected")

    try:
        async for message in ws:
            print("Received:", message)
    except:
        pass
    finally:
        clients.remove(ws)
        print("Client disconnected")

async def broadcast(data):
    if clients:
        msg = json.dumps(data)
        await asyncio.gather(*(c.send(msg) for c in clients))

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("WebSocket running on port 8080")
        await asyncio.Future()

asyncio.run(main())
