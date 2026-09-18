from datetime import datetime, timedelta
from typing import Annotated

import bcrypt
from chat import models
from chat.database import get_db
from chat.schema import TokenData, User
from chat.setting import setting
from chat.utils.exception import CredentialsException
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# NOTE: `Base.metadata.create_all(bind=engine)` used to run here at import time.
# That was a sync call against a sync engine - it can't work against the new
# async engine. Table creation now happens via chat.database.init_models(),
# called once from your FastAPI startup event in chat/__init__.py.
# See PHASE1_SETUP.md for the exact snippet to add there.


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies if the provided plain text password matches the stored hashed password.
    """
    encoded_hashed_password = hashed_password.encode("utf-8")
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        encoded_hashed_password,
    )


def get_password_hash(password: str) -> str:
    """
    Generates a bcrypt hash for the provided password.
    """
    hashed_bytes = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed_bytes.decode("utf-8")


async def get_user(user_db: AsyncSession, username: str) -> models.User | None:
    """
    Retrieve a user from the database based on the username.

    Eager-loads `unread_messages` (and each one's `.message`) because
    chat/crud.py's get_reads_messages() and chat/views/websocket.py's
    catch-up delivery both read user.unread_messages / unread.message after
    this coroutine returns - lazy-loading on an AsyncSession raises
    MissingGreenlet if you don't load it up front.
    """
    result = await user_db.execute(
        select(models.User)
        .options(
            selectinload(models.User.unread_messages).selectinload(
                models.UnreadMessage.message
            )
        )
        .filter(models.User.username == username)
    )
    return result.scalar_one_or_none()


async def authenticate_user(
    user_db: AsyncSession, username: str, password: str
) -> models.User | None:
    """
    Authenticate a user based on the provided username and password.
    """
    user = await get_user(user_db, username)
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Create an access token with the provided data.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    to_encode["id"] = int(to_encode.get("id"))
    encoded_jwt = jwt.encode(
        to_encode,
        setting.SECRET_KEY,
        algorithm=setting.ALGORITHM,
    )
    return encoded_jwt


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    user_db: AsyncSession = Depends(get_db),
) -> User:
    """
    Get the current authenticated user from the provided token.
    """
    token_data = decode_jwt(token)
    user = await get_user(user_db, username=token_data.username)
    if user is None:
        raise CredentialsException
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Get the current active authenticated user.
    """
    if current_user.disabled:
        raise HTTPException(
            status_code=400, detail="Inactive user"
        )  # TODO Add this to Exceptions
    return current_user


def get_admin_payload(token: str) -> dict | None:
    """
    Decode the payload of the provided JWT token for admin user.
    """
    try:
        payload = jwt.decode(token, setting.SECRET_KEY, setting.ALGORITHM)
        username: str = payload.get("username")
        id: int = int(payload.get("id"))
        return {"username": username, "id": id}
    except JWTError:
        return


def decode_jwt(
    token: Annotated[str, Depends(oauth2_scheme)]
) -> TokenData | CredentialsException:
    """
    Decode the provided JWT token and extract the token data.
    """
    try:
        payload = jwt.decode(
            token,
            setting.SECRET_KEY,
            algorithms=[setting.ALGORITHM],
        )
        username: str = payload.get("username")
        user_id: int = int(payload.get("id"))
        if username is None or user_id is None:
            raise CredentialsException
        token_data = TokenData(username=username, id=user_id)
    except JWTError:
        raise CredentialsException
    return token_data
