"""Shared fixtures for DB-backed tests.

Tests NEVER touch the dev database (fleet_agent_test only), and NEVER inherit
the developer's .env (redirected to /dev/null before any app module loads).
The test database is created once via:
  docker compose exec -T postgres psql -U fleet -d postgres \
    -c "CREATE DATABASE fleet_agent_test;"
"""

import os

_LLM_LIVE_KEYS = (
    "FLEET_AGENT_LLM_MODEL",
    "FLEET_AGENT_LLM_BASE_URL",
    "FLEET_AGENT_LLM_API_KEY",
)
# Ambient local provider defaults (Settings reads these unprefixed) must not
# leak from the developer's shell into the test suite.
_MODAL_AMBIENT_KEYS = (
    "MODAL_API_KEY",
    "MODAL_BASE_URL",
    "MODAL_MODEL_ID",
)
_TEST_DB_URL = "postgresql+asyncpg://fleet:fleet@localhost:5432/fleet_agent_test"


def purge_ambient_settings_env() -> None:
    """Remove ambient FLEET_AGENT_*/MODAL_* from os.environ so Settings
    defaults dominate. RUN_ENGINE_LIVE_TEST=1 keeps LLM credentials (live
    provider smoke only)."""
    keep_llm = bool(os.environ.get("RUN_ENGINE_LIVE_TEST"))
    for key in [k for k in os.environ if k.startswith("FLEET_AGENT_")]:
        if key == "FLEET_AGENT_ENV_FILE":
            continue
        if keep_llm and key in _LLM_LIVE_KEYS:
            continue
        os.environ.pop(key, None)
    if not keep_llm:
        for key in _MODAL_AMBIENT_KEYS:
            os.environ.pop(key, None)
    os.environ["FLEET_AGENT_ENV_FILE"] = "/dev/null"
    os.environ["FLEET_AGENT_DATABASE_URL"] = _TEST_DB_URL


# HARD WALL: set BEFORE any app module import so Settings' env_file is defused.
purge_ambient_settings_env()


import asyncio  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.persistence.db import build_engine, build_sessionmaker  # noqa: E402
from app.settings import Settings, get_settings  # noqa: E402

get_settings.cache_clear()

_SETTINGS = Settings(
    database_url="postgresql+asyncpg://fleet:fleet@localhost:5432/fleet_agent_test"  # type: ignore[arg-type]
)


def _probe(url: str) -> bool:
    async def check() -> bool:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect():
                return True
        except (SQLAlchemyError, OSError):
            return False
        finally:
            await engine.dispose()

    try:
        return asyncio.run(check())
    except Exception:
        return False


DB_IS_UP = _probe(_SETTINGS.database_url.get_secret_value())

requires_db = pytest.mark.skipif(not DB_IS_UP, reason="postgres unreachable")


@pytest.fixture()
def db_settings() -> Settings:
    return _SETTINGS


@pytest.fixture()
async def db_sessions(db_settings):
    engine = build_engine(db_settings)
    sessions = build_sessionmaker(engine)
    # Start each test from empty tables (fast: truncate, not drop).
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "TRUNCATE messages, runs, run_states, dspy_histories, threads, projects "
            "RESTART IDENTITY CASCADE"
        )
    yield sessions
    await engine.dispose()


def make_test_app(**env_overrides: str):
    """create_app() with env-backed settings — middleware/semaphore/metrics are
    built AT CONSTRUCTION TIME, so tests must configure via env, not state."""
    from app.main import create_app
    from app.settings import get_settings

    keys = {key: f"FLEET_AGENT_{key.upper()}" for key in env_overrides}
    saved = {env_key: os.environ.get(env_key) for env_key in keys.values()}
    try:
        for key, env_key in keys.items():
            value = env_overrides[key]
            if value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = value
        get_settings.cache_clear()
        return create_app()
    finally:
        for env_key, value in saved.items():
            if value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = value
        get_settings.cache_clear()


@pytest.fixture()
async def live_server_factory():
    """Starts apps on real loopback sockets — required for in-flight streaming
    behavior (ASGITransport serializes streams)."""
    import socket

    import uvicorn

    servers = []

    async def start(app) -> str:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        servers.append((server, task))
        return f"http://127.0.0.1:{port}"

    yield start

    for server, task in servers:
        server.should_exit = True
        await task


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup():
    """Per-test isolation: litellm's import-time load_dotenv re-injects .env
    into os.environ — purge before EVERY test (see purge_ambient_settings_env)."""
    purge_ambient_settings_env()
    from app.settings import get_settings

    get_settings.cache_clear()
