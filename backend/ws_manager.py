import json
from fastapi import WebSocket


class WSManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        if hasattr(ws, "accept"):
            try:
                await ws.accept()
            except Exception:
                pass
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: dict):
        message = json.dumps(data, ensure_ascii=False)
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)

    async def send_full_state(self, ws: WebSocket, agents: list[dict]):
        await ws.send_text(json.dumps({
            "type": "full_state",
            "agents": agents,
        }, ensure_ascii=False))
