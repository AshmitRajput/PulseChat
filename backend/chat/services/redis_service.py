import redis.asyncio as redis

from chat.setting import setting

redis_client = redis.from_url(setting.REDIS_URL, decode_responses=True)


def channel_for_user(user_id: int) -> str:
    """Every backend instance that has this user's live socket subscribes here."""
    return f"chat:user:{user_id}"


def channel_for_group(group_id: int) -> str:
    """Reserved for later (e.g. typing indicators broadcast to a whole room
    without per-member fan-out). Not used yet in Phase 1."""
    return f"chat:room:{group_id}"
