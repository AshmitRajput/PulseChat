import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from chat.database import init_models

__version__ = "1"
app = FastAPI(
    title="ChatProvider",
    description="A ChatProvider Based on WebSocket",
    version=__version__,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # was `["*"]` - CORSMiddleware expects a bool here, not a list
    allow_methods=["*"],
    allow_headers=["*"],
)
logger = logging.getLogger("uvicorn.error")


@app.on_event("startup")
async def on_startup() -> None:
    """Creates tables against the async engine. Replaces the old
    `Base.metadata.create_all(bind=engine)` call that used to sit in
    chat/utils/jwt.py - that was sync and can't run against create_async_engine."""
    await init_models()
