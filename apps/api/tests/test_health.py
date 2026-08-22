import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import requires_db


@pytest.fixture
def app():
    return create_app()


async def test_health(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


test_ready = requires_db(test_ready)


async def test_ready_503_when_database_down():
    from app.persistence.db import build_engine, build_sessionmaker

    app = create_app()
    app.state.db_engine = build_engine(
        Settings(
            database_url="postgresql+asyncpg://fleet:fleet@127.0.0.1:1/fleet_agent"  # type: ignore[arg-type]
        )
    )
    app.state.db_sessions = build_sessionmaker(app.state.db_engine)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "down"}


async def test_cors_allows_configured_origin_only(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        allowed = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        rejected = await client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in rejected.headers


async def test_agui_protocol_imports():
    """Smoke check: the AG-UI SDK surface the mock endpoint (PR 3) needs."""
    from ag_ui.core import EventType, TextMessageContentEvent
    from ag_ui.encoder import EventEncoder

    encoder = EventEncoder()
    encoded = encoder.encode(
        TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT, message_id="m1", delta="hi"
        )
    )
    assert encoded.startswith("data: ")
