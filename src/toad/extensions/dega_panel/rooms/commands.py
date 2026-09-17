"""Local agent command contract for the same room service used by the UI."""

from toad.extensions.dega_panel.rooms.protocol import RoomError, require
from toad.extensions.dega_panel.rooms.service import RoomService


async def execute(service: RoomService, request: dict) -> dict:
    """Execute a room command and return JSON-serializable results.

    Args:
        service: The current identity's room service.
        request: Local socket payload with action and its required arguments.
    """
    action = request.get("action", "")
    require(isinstance(action, str), "action must be text")
    if action == "list":
        return {"rooms": await service.rooms()}
    if action == "create":
        return {"room_id": await service.create_room(request.get("name", ""))}
    if action == "retry":
        await service.flush()
        return {"ok": True}
    room_id = request.get("room_id")
    if not isinstance(room_id, str):
        raise RoomError("invalid_payload", "room_id is required")
    return await _room_command(service, action, room_id, request)


async def _room_command(service: RoomService, action: str, room_id: str, request: dict) -> dict:
    if action == "invite":
        return {"operation_id": await service.invite(room_id, request.get("pubkey", ""))}
    if action == "respond":
        require(type(request.get("accept")) is bool, "accept must be true or false")
        return {"operation_id": await service.respond(room_id, request["accept"])}
    if action == "send":
        return {"operation_id": await service.send(room_id, request.get("text", ""))}
    if action == "history":
        return {"messages": await service.history(room_id)}
    if action == "members":
        room = next((item for item in await service.rooms() if item["id"] == room_id), None)
        require(room is not None, "Room not found")
        return {"room": room}
    return await _manage_command(service, action, room_id, request)


async def _manage_command(service: RoomService, action: str, room_id: str, request: dict) -> dict:
    if action == "leave":
        await service.leave(room_id)
    elif action in {"remove", "rename", "close"}:
        value = request.get("name", "") if action == "rename" else request.get("pubkey", "")
        await service.manage(room_id, action, value)
    else:
        raise RoomError("invalid_payload", "Unknown room action")
    return {"ok": True}
