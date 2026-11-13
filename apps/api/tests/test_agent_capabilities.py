import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.contracts.agent_capabilities import AgentCapabilities
from tests.conftest import make_test_app


@pytest.mark.parametrize("mode", ["fixtures", "engine"])
async def test_capabilities_report_mode_and_require_configured_auth(mode):
    app = make_test_app(agent_mode=mode, api_key="fixture-api-key")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.get("/api/agent/capabilities")
        allowed = await client.get(
            "/api/agent/capabilities", headers={"X-API-Key": "fixture-api-key"}
        )
    assert denied.status_code == 401
    assert allowed.status_code == 200
    # tests/conftest.py clears every FLEET_AGENT_LLM_* value, so this
    # deployment has no server-side gateway of its own.
    assert allowed.json() == {
        "agent_mode": mode,
        "supported_content_types": ["text"],
        "server_gateway_configured": False,
    }


async def test_capabilities_report_a_configured_server_gateway():
    """A server-side key is what makes a headerless run possible.

    Both LM paths require it: without a base URL DSPy's hosted lm15 router needs
    the key to select a provider, and with a base URL ``GatewayEngine``
    registers the credential per router, so an empty key map raises
    ``NotConfiguredError`` at call time.
    """
    app = make_test_app(
        agent_mode="engine",
        api_key="fixture-api-key",
        llm_api_key="sk-test-server-gateway",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/agent/capabilities", headers={"X-API-Key": "fixture-api-key"}
        )
    assert response.status_code == 200
    assert response.json()["server_gateway_configured"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        # A base URL alone cannot start a run: GatewayEngine registers its
        # credential per router, so lm15 raises NotConfiguredError with an
        # empty key map. Verified against a live gateway during this change.
        {"llm_base_url": "https://gateway.example/v1"},
        {},
    ],
)
async def test_capabilities_report_no_gateway_without_a_server_key(overrides):
    app = make_test_app(agent_mode="engine", api_key="fixture-api-key", **overrides)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/agent/capabilities", headers={"X-API-Key": "fixture-api-key"}
        )
    assert response.status_code == 200
    assert response.json()["server_gateway_configured"] is False


@pytest.mark.parametrize(
    "value",
    [
        {"agent_mode": "unknown"},
        {"agent_mode": 1},
        {"agent_mode": "fixtures", "api_key": "unexpected"},
        {
            "agent_mode": "fixtures",
            "supported_content_types": ["text"],
            "server_gateway_configured": ["not", "a", "boolean"],
        },
    ],
)
def test_capabilities_contract_is_strict(value):
    with pytest.raises(ValidationError):
        AgentCapabilities.model_validate(value)


def test_capabilities_accept_an_older_server_without_the_gateway_field():
    """The field is optional, so an older payload still validates.

    Absence must not be read as "not configured": the browser treats it as
    unknown and keeps the composer failing closed.
    """
    model = AgentCapabilities.model_validate(
        {"agent_mode": "engine", "supported_content_types": ["text"]}
    )
    assert model.server_gateway_configured is None


def test_generated_capabilities_are_fresh():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            "uv",
            "run",
            "datamodel-codegen",
            "--input",
            str(root / "packages/contracts/agent-capabilities.schema.json"),
            "--input-file-type",
            "jsonschema",
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--target-python-version",
            "3.13",
            "--use-union-operator",
            "--use-title-as-name",
            "--enum-field-as-literal",
            "all",
            "--disable-timestamp",
            "--formatters",
            "ruff-check",
            "ruff-format",
        ],
        cwd=root / "apps/api",
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        result.stdout
        == (root / "apps/api/app/contracts/agent_capabilities.py").read_text()
    )
