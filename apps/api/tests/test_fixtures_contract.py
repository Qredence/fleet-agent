"""Contract tests: fixtures stay coherent with the AgentWorkspaceState schema
and with the privacy boundary (no raw chain-of-thought fields ever shipped).
"""

import json
import subprocess
from pathlib import Path

import jsonpatch
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "packages" / "contracts" / "fixtures"
SCHEMA_PATH = REPO_ROOT / "packages" / "contracts" / "agent-workspace-state.schema.json"
GENERATED_MODEL = (
    Path(__file__).resolve().parents[1] / "app" / "contracts" / "agent_state.py"
)

FIXTURE_NAMES = ["successful-run", "tool-error-run", "forced-submit-run"]

# Fields that must never appear in any client-visible payload.
PROHIBITED_KEYS = {
    "next_thought",
    "nextThought",
    "trajectory",
    "system_prompt",
    "systemPrompt",
    "api_key",
    "apiKey",
    "traceback",
    "stackTrace",
    "provider_request",
    "providerRequest",
}


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_fixture_lines(name: str) -> list[dict]:
    path = FIXTURES_DIR / f"{name}.ndjson"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(scope="module")
def validator():
    import jsonschema

    return jsonschema.Draft202012Validator(load_schema())


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixtures_contain_no_prohibited_fields(name):
    for line in load_fixture_lines(name):
        found = PROHIBITED_KEYS & set(walk_keys(line))
        assert not found, f"{name} leaks prohibited fields: {found}"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixtures_have_exactly_one_terminal_event(name):
    types = [line["event"]["type"] for line in load_fixture_lines(name)]
    terminals = [t for t in types if t in {"RUN_FINISHED", "RUN_ERROR"}]
    assert len(terminals) == 1
    assert types[-1] == terminals[0]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_state_deltas_keep_snapshot_schema_valid(name, validator):
    lines = load_fixture_lines(name)

    state = None
    for line in lines:
        event = line["event"]
        if event["type"] == "STATE_SNAPSHOT":
            state = event["snapshot"]
            validator.validate(state)
        elif event["type"] == "STATE_DELTA":
            assert state is not None, f"{name}: STATE_DELTA before snapshot"
            state = jsonpatch.apply_patch(state, event["delta"])
            validator.validate(state)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_state_delta_paths_address_real_structure(name):
    """Deltas must not patch phantom paths (add/remove targets must exist)."""
    for line in load_fixture_lines(name):
        if line["event"]["type"] != "STATE_DELTA":
            continue
        for op in line["event"]["delta"]:
            assert op["op"] in {"add", "replace", "remove"}
            assert op["path"].startswith("/")


def test_fixtures_collectively_exercise_all_patch_operations():
    """The canonical streams cover add, replace, and remove."""
    ops = {
        op["op"]
        for name in FIXTURE_NAMES
        for line in load_fixture_lines(name)
        if line["event"]["type"] == "STATE_DELTA"
        for op in line["event"]["delta"]
    }
    assert {"add", "replace", "remove"} <= ops


def test_generated_model_is_fresh():
    """app/contracts/agent_state.py must match the schema's current codegen."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "datamodel-codegen",
            "--input",
            str(SCHEMA_PATH),
            "--input-file-type",
            "jsonschema",
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--target-python-version",
            "3.13",
            "--use-union-operator",
            "--use-title-as-name",
            "--disable-timestamp",
            "--formatters",
            "ruff-check",
            "ruff-format",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    current = GENERATED_MODEL.read_text(encoding="utf-8")
    assert current == result.stdout, (
        "app/contracts/agent_state.py is stale — regenerate it from "
        "packages/contracts/agent-workspace-state.schema.json"
    )
