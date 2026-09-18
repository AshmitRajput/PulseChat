import asyncio
import json

from fastapi import Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from chat import app, logger, models
from chat.crud import (
    create_message_controller,
    create_unread_message_controller,
    get_group_by_id,
    group_membership_check,
)
from chat.database import get_db
from chat.models import Message
from chat.services.presence import mark_offline, mark_online
from chat.services.redis_service import channel_for_user, redis_client
from chat.utils.jwt import get_current_user

# NOTE: the old `websocket_connections = {}` module-level dict and the
# `user.websocket = websocket` attribute assignment are GONE. Neither can
# work once you run more than one backend process - a process only ever
# knows about sockets it personally holds. Redis is now the only source of
# truth for "who gets this event", via per-user channels.


@app.websocket("/send-message")
async def send_messages_endpoint(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    User send/receive message socket (this endpoint now also replaces the old
    /get-unread-messages socket - see the catch-up block below).
    - token [str]
    - group_id [int]

    [in websocket, client -> server]
    - text (plain string, same wire format as before for Phase 1)

    [out websocket, server -> client]
    - JSON: {"type": "Text"|"change", ...}
    """
    token = websocket.query_params.get("token")
    group_id = websocket.query_params.get("group_id")
    if token and group_id:
        user = await get_current_user(user_db=db, token=token)
        group_id = int(group_id)
    else:
        return await websocket.close(reason="You're not allowed", code=4403)

    is_group_member = await group_membership_check(group_id=group_id, db=db, user=user)
    if not is_group_member:
        logger.error(
            "User %s Connect to Send Messages But not allowed with group id : %s",
            user.username,
            group_id,
        )
        return await websocket.close(reason="You're not allowed", code=4403)

    logger.info(
        "User %s Connect to Send Messages endpoint group id : %s",
        user.username,
        group_id,
    )
    await websocket.accept()
    await mark_online(user.id)

    # --- catch-up: flush anything that arrived while this user was offline ---
    await send_messages_concurrently(websocket, user.unread_messages)
    for unread in list(user.unread_messages):
        await db.delete(unread)
    await db.commit()

    # --- go live: subscribe this connection to its own Redis channel ---
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel_for_user(user.id))
    listener_task = asyncio.create_task(_relay_redis_to_socket(pubsub, websocket))

    try:
        while True:
            data = await websocket.receive_text()
            if data is None:
                break
            await mark_online(user.id)  # cheap presence refresh; Phase 2 adds a real heartbeat frame
            message = await create_message_controller(
                db=db, user=user, group_id=group_id, text=data
            )
            await publish_new_message(group_id, message, db)
    except WebSocketDisconnect as error_message:
        logger.info(
            "User %s Disconnect from Send Messages endpoint group id : %s, %s",
            user.username,
            group_id,
            error_message,
        )
    finally:
        listener_task.cancel()
        await pubsub.unsubscribe(channel_for_user(user.id))
        await pubsub.aclose()
        await mark_offline(user.id)


async def _relay_redis_to_socket(pubsub, websocket: WebSocket) -> None:
    """Forwards anything published to this user's Redis channel straight to
    their live socket. Runs as a background task for the lifetime of the
    connection; cancelled on disconnect."""
    try:
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            await websocket.send_text(msg["data"])
    except asyncio.CancelledError:
        pass


async def publish_new_message(group_id: int, message: Message, db) -> None:
    """
    Persist-then-publish: the message row already exists (created by the
    caller) before this fans the event out, so Postgres always has it even
    if Redis or every subscriber is briefly unavailable.
    - group_id [int]
    - message [Message]

    output:
    - None
    """
    group = await get_group_by_id(db=db, group_id=group_id)
    if not group:
        return
    payload = json.dumps(
        {
            "type": "Text",
            "id": message.id,
            "text": message.text,
            "sender_name": message.sender_name,
            "datetime": str(message.created_at),
        }
    )
    for member in group.members:
        await create_unread_message_controller(
            db=db,
            message=message,
            user=member.user,
            group_id=group_id,
        )
        await redis_client.publish(channel_for_user(member.user_id), payload)


async def broadcast_changes(
    group_id: int,
    change_type: models.ChangeType,
    db: AsyncSession,
    message_id: int | None = None,
    new_text: str | None = None,
) -> None:
    """
    broadcast edit/delete changes to all group members via Redis (delivered
    only to whichever backend instance currently holds that member's socket -
    Redis pub/sub handles the cross-instance part automatically).
    - group_id [int]
    - change_type [str]
    - message_id [int]
    - new_text [str]

    output:
    - None
    """
    group = await get_group_by_id(db=db, group_id=group_id)
    if not group:
        return
    changed_value = json.dumps(
        {
            "type": change_type,
            "id": message_id,
            "new_text": new_text,
        }
    )
    await asyncio.gather(
        *[
            redis_client.publish(channel_for_user(member.user_id), changed_value)
            for member in group.members
        ]
    )


async def send_messages_concurrently(
    websocket: WebSocket, messages: list[models.UnreadMessage]
):
    """Send Messages"""
    if not messages:
        return
    tasks = [
        websocket.send_text(
            json.dumps(
                {
                    "text": message.message.text,
                    "sender_name": message.message.sender_name,
                    "id": message.message.id,
                    "type": "Text",
                    "datetime": str(message.message.created_at),
                }
            )
        )
        for message in messages
    ]
    await asyncio.gather(*tasks)
