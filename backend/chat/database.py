from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# NOTE: driver changed from postgresql+psycopg (sync) to postgresql+asyncpg (async).
# Update the DSN below if your real credentials/host differ.
engine = create_async_engine(
    "postgresql+asyncpg://root:1234@db/postgres",
    pool_size=20,
    max_overflow=10,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as db:
        yield db


async def init_models() -> None:
    """Create tables on startup. Call this once from chat/__init__.py's startup event
    (see PHASE1_SETUP.md - this replaces the old sync Base.metadata.create_all call
    that used to live in chat/utils/jwt.py)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
