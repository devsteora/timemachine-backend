from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from typing import Dict

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def broadcast_status(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws/status/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            # Expecting data like {"status": "ACTIVE", "app": "VS Code"}
            data["user_id"] = user_id 
            await manager.broadcast_status(data)
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        await manager.broadcast_status({"user_id": user_id, "status": "OFFLINE"})