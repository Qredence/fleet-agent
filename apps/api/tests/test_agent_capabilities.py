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
    assert allowed.json() == {"agent_mode": mode}


@pytest.mark.parametrize(
    "value",
    [
        {"agent_mode": "unknown"},
        {"agent_mode": 1},
        {"agent_mode": "fixtures", "api_key": "unexpected"},
    ],
)
def test_capabilities_contract_is_strict(value):
    with pytest.raises(ValidationError):
        AgentCapabilities.model_validate(value)


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
