from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from chat import models, schema
from chat.utils.jwt import get_password_hash


async def create_user_controller(
    db: AsyncSession,
    user: schema.CreateUser,
) -> models.User | None:
    result = await db.execute(
        select(models.User).filter(models.User.username == user.username)
    )
    existing_user = result.scalar_one_or_none()
    if existing_user:
        return None
    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        password=hashed_password,
        email=user.email,
        display_name=user.full_name,
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


async def create_group_controller(
    db: AsyncSession, group: schema.GroupCreate
) -> models.Group:
    new_group = models.Group(address=group.address, name=group.name)
    db.add(new_group)
    await db.commit()
    await db.refresh(new_group)
    return new_group


async def create_message_controller(
    db: AsyncSession, user: models.User, group_id: int, text: str
) -> models.Message:
    message = models.Message(
        text=text, sender_id=user.id, sender_name=user.username, group_id=group_id
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def create_unread_message_controller(
    db: AsyncSession,
    user: schema.CreateUser,
    message: models.Message,
    group_id: int,
) -> models.UnreadMessage:
    unread_message = models.UnreadMessage(
        user_id=user.id,
        user_name=user.username,
        message_id=message.id,
        group_id=group_id,
    )
    db.add(unread_message)
    await db.commit()
    return unread_message


async def group_membership_check(
    group_id: int, db: AsyncSession, user: schema.User
) -> models.GroupMember | None:
    result = await db.execute(
        select(models.GroupMember).filter(
            models.GroupMember.group_id == group_id,
            models.GroupMember.user_id == user.id,
        )
    )
    return result.scalar_one_or_none()


async def group_members_by_id(
    group_id: int,
    db: AsyncSession,
) -> list[models.User]:
    result = await db.execute(
        select(models.User)
        .join(models.GroupMember)
        .filter(models.GroupMember.group_id == group_id)
    )
    return list(result.scalars().all())


async def get_group_by_id(
    group_id: int,
    db: AsyncSession,
) -> models.Group | None:
    """Eager-loads members + each member's user, because websocket.py iterates
    group.members -> member.user AFTER this coroutine returns. Without
    selectinload, that lazy access crashes async SQLAlchemy (MissingGreenlet)."""
    result = await db.execute(
        select(models.Group)
        .options(selectinload(models.Group.members).selectinload(models.GroupMember.user))
        .filter_by(id=group_id)
    )
    return result.scalar_one_or_none()


async def get_group_by_address(
    address: str,
    db: AsyncSession,
) -> models.Group | None:
    result = await db.execute(select(models.Group).filter_by(address=address))
    return result.scalar_one_or_none()


async def join_member_to_group(
    db: AsyncSession,
    user: schema.User,
    group: models.Group,
    role: schema.UserRole = schema.UserRole.member,
):
    group_member = models.GroupMember(
        user_id=user.id,
        group_id=group.id,
        role=role,
    )
    db.add(group_member)
    await db.commit()


async def get_user_by_id(
    user_id: int,
    db: AsyncSession,
) -> models.User | None:
    result = await db.execute(select(models.User).filter(models.User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_groups_by_id(
    user_id: int,
    db: AsyncSession,
) -> list[models.Group]:
    result = await db.execute(
        select(models.Group)
        .join(models.GroupMember)
        .filter(models.GroupMember.user_id == user_id)
    )
    return list(result.scalars().all())


async def get_message_by_id(
    message_id: int,
    user_id: int,
    db: AsyncSession,
) -> models.Message | None:
    result = await db.execute(
        select(models.Message).filter(models.Message.id == message_id)
    )
    message = result.scalar_one_or_none()
    if message and user_id == message.sender_id:
        return message
    return None


async def get_reads_messages(
    group_id: int,
    user: schema.User,
    db: AsyncSession,
) -> list[models.Message] | None:
    # NOTE: user.unread_messages must already be eager-loaded on the `user`
    # object passed in (get_current_user in jwt.py now loads it eagerly -
    # see the updated jwt.py). Accessing it lazily here would crash.
    unread_message_ids = [
        unread_message.message_id for unread_message in user.unread_messages
    ]
    result = await db.execute(
        select(models.Message)
        .filter(models.Message.group_id == group_id)
        .filter(models.Message.id.notin_(unread_message_ids))
        .order_by(models.Message.id)
    )
    return list(result.scalars().all())


async def get_first_unread_message_group(
    group_id: int,
    user: schema.User,
    db: AsyncSession,
) -> models.Message | None:
    result = await db.execute(
        select(models.Message)
        .join(models.UnreadMessage)
        .filter(
            models.Message.group_id == group_id,
            models.UnreadMessage.user_id == user.id,
        )
        .order_by(models.Message.id)
    )
    return result.scalars().first()


async def create_change_controller(
    db: AsyncSession,
    new_text: str,
    original_text: str,
    changes_type: models.ChangeType,
    sender_id: int,
    group_id: int,
) -> models.Changes:
    change = models.Changes(
        new_text=new_text,
        original_text=original_text,
        changes_type=changes_type,
        sender_id=sender_id,
        group_id=group_id,
    )
    db.add(change)
    await db.commit()
    return change


async def get_changes_by_group(
    db: AsyncSession,
    group_id: int,
) -> list[models.Changes] | None:
    result = await db.execute(
        select(models.Changes).filter(models.Changes.group_id == group_id)
    )
    return list(result.scalars().all())


async def delete_changes_by_group(
    db: AsyncSession,
    group_id: int,
) -> None:
    await db.execute(delete(models.Changes).filter(models.Changes.group_id == group_id))
    await db.commit()


async def edit_message(
    db: AsyncSession,
    changed_message: str,
    message: models.Message,
) -> models.Message:
    message.text = changed_message
    await db.commit()
    return message


async def delete_message(
    db: AsyncSession,
    message: models.Message,
) -> None:
    result = await db.execute(
        select(models.UnreadMessage).filter_by(message_id=message.id)
    )
    unread_message = result.scalar_one_or_none()
    if unread_message:
        await db.delete(unread_message)
    await db.delete(message)
    await db.commit()
