# Phase 1 setup notes

## Files in this drop
Replace these in your repo as-is (they're your real files, fully converted - no manual edits needed anymore):
```
docker-compose.yaml                    (repo root - adds redis, fixes depends_on race)
backend/requirements.txt               (adds pydantic-settings, redis, asyncpg)
backend/Dockerfile
backend/chat/__init__.py               (startup hook + CORS bool fix)
backend/chat/setting.py                (was broken: `class Settings(auto)` - fixed + REDIS_URL added)
backend/chat/database.py
backend/chat/crud.py
backend/chat/utils/jwt.py
backend/chat/views/auth.py
backend/chat/views/groups.py
backend/chat/views/messages.py
backend/chat/views/user.py
backend/chat/views/websocket.py
backend/chat/services/__init__.py      (new)
backend/chat/services/redis_service.py (new)
backend/chat/services/presence.py      (new)
```
`models.py`, `schema.py`, `exception.py` are unchanged in Phase 1 - don't overwrite them.

## What was actually wrong in the three files you sent, for the record
1. **`chat/setting.py`** - `class Settings(auto):` inherited from `enum.auto`, which is meaningless here (copy-paste leftover). Fixed to `pydantic_settings.BaseSettings` and added `REDIS_URL`.
2. **`chat/__init__.py`** - `allow_credentials=["*"]` in CORS middleware is wrong type (expects `bool`); fixed to `True`. Also had no startup hook, which is why `Base.metadata.create_all` was still living in `jwt.py` at import time and crashing before Postgres was ready.
3. **`docker-compose.yaml`** - no `redis` service at all (Phase 1 code would crash the moment a socket tries to connect), and `app`'s `depends_on: - db` only waited for the container to start, not for Postgres to accept connections - that's exactly the race that produced the traceback you hit. Fixed with `condition: service_healthy` on both `db` and the new `redis` service. Also dropped the `sleep 3s` hack in `command` since the healthcheck-gated `depends_on` makes it unnecessary, and removed the obsolete top-level `version: '3'` key.

## Install & run
```bash
docker compose down -v          # -v clears the old db volume; skip -v if you want to keep existing data
docker compose build --no-cache
docker compose up -d
docker compose logs -f app
```
Watch for `Application startup complete` with **no traceback above it**. If you see the old `Base.metadata.create_all` / `Connection refused` traceback again, the container is still running a stale image - confirm `chat/__init__.py` and `chat/utils/jwt.py` in the built image actually match what's in this drop (`docker compose exec app cat chat/__init__.py` from `/app/backend`, adjust path if needed).

```bash
curl http://localhost:8000/health
docker compose ps               # db, redis, app, nginx should all show healthy/running
```

## How to verify Phase 1 actually works (don't skip this)
1. **Single instance sanity check** - log in as two users, join the same group, send a message from one, confirm the other receives it live over `/send-message`.
2. **Cross-instance check (the actual point of this phase)** - run two backend containers on different ports pointed at the same Postgres + Redis:
   ```bash
   docker compose up -d --scale backend=2
   ```
   Connect Client A's websocket to instance 1's port, Client B's to instance 2's port, same group. Send from A, confirm B receives it via Redis even though they're on different processes. This is the test that proves the in-memory dict removal actually solved the problem.
3. **Presence check** - hit a route that calls `presence.is_online(user_id)` (or check the Redis key directly with `redis-cli GET presence:user:<id>`) while a socket is open, then again ~35s after closing it - should flip to offline once the TTL expires.
4. **Catch-up check** - with User B's socket closed, send a message to their group from User A, then reconnect B - confirm B receives the missed message once on reconnect (not zero times, not looping every poll like the old `/get-unread-messages` did).

Once all four pass, Phase 1 is done - move to Phase 2 (ACKs/heartbeat/reconnect) in the master plan doc.
