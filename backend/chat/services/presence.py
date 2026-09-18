from chat.services.redis_service import redis_client

PRESENCE_TTL_SECONDS = 30


async def mark_online(user_id: int) -> None:
    """Call on socket connect and on every received message/heartbeat.
    Key expires automatically if the client goes silent -> "offline"."""
    await redis_client.set(f"presence:user:{user_id}", "online", ex=PRESENCE_TTL_SECONDS)


async def is_online(user_id: int) -> bool:
    return await redis_client.get(f"presence:user:{user_id}") is not None


async def mark_offline(user_id: int) -> None:
    """Optional: call explicitly on clean disconnect so the user shows offline
    immediately instead of waiting out the TTL."""
    await redis_client.delete(f"presence:user:{user_id}")
