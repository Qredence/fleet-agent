"""Architectural boundaries, enforced by reading the source tree.

A boundary that only lives in prose gets crossed. These tests fail when a
dependency the design depends on is reintroduced.

The rule is simple: the agent layer must be buildable, testable, and optimizable
without a web server, a database, or the transport that happens to serve it.
``evals/optimize.py`` imports it, and an offline optimizer has no business
needing any of those.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
AGENT = APP / "agent"

# Third-party roots the agent layer must never import.
FORBIDDEN_THIRD_PARTY = (
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "asyncpg",
    "alembic",
)

# Application layers that depend ON the agent, so the agent must not import them.
FORBIDDEN_APP_LAYERS = ("app.agui", "app.api", "app.persistence", "app.main")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return found


def _agent_violations(forbidden: tuple[str, ...]) -> list[str]:
    """Return imports of a forbidden module or any of its submodules.

    Prefix matching, not ``split(".")[0]``: the app-layer entries are dotted
    (``app.agui``), so comparing only the first segment would compare ``"app"``
    against ``"app.agui"`` and never match - a guard that silently passes.
    """
    violations: list[str] = []
    for path in sorted(AGENT.rglob("*.py")):
        for module in _imports(path):
            if any(
                module == banned or module.startswith(f"{banned}.")
                for banned in forbidden
            ):
                violations.append(f"{path.relative_to(APP.parent)}: {module}")
    return violations


def test_the_agent_layer_has_no_web_or_database_dependency() -> None:
    violations = _agent_violations(FORBIDDEN_THIRD_PARTY)
    assert violations == [], (
        "the agent layer must stay free of web and database dependencies so it "
        f"can be built and optimized on its own: {violations}"
    )


def test_the_agent_layer_does_not_import_the_layers_that_serve_it() -> None:
    """The transport and the HTTP layer depend on the agent, never the reverse.

    ``event_bus``, ``cancel_token`` and the ``EngineBuilder`` contract live in the
    agent layer precisely so this direction holds; moving them back would make the
    two layers import each other.
    """
    violations = _agent_violations(FORBIDDEN_APP_LAYERS)
    assert violations == [], (
        f"the agent layer must not depend on its own transport or API: {violations}"
    )


def test_the_agui_layer_imports_the_agent_contracts_it_consumes() -> None:
    """A guard against the mirror image: the shared contracts stay agent-owned."""
    event_bus = (AGENT / "event_bus.py").resolve()
    cancel_token = (AGENT / "cancel_token.py").resolve()
    assert event_bus.is_file(), "RunEventBus belongs to the agent layer"
    assert cancel_token.is_file(), "RunCancelToken belongs to the agent layer"

    engine = (AGENT / "engine.py").read_text(encoding="utf-8")
    assert "class EngineBuilder(Protocol):" in engine, (
        "the engine build contract belongs beside the engine it produces"
    )


# --- configuration truth ----------------------------------------------------

SETTINGS = APP / "settings.py"
ENV_EXAMPLE = APP.parent / ".env.example"

# Fields read from unprefixed environment names, not the FLEET_AGENT_ prefix.
_UNPREFIXED_ALIASES = {"MODAL_API_KEY", "MODAL_BASE_URL", "MODAL_MODEL_ID"}


def _settings_env_names() -> set[str]:
    """The environment name of every ``Settings`` field.

    Parsed per field annotation, not with a file-wide regex: a greedy pattern
    cross-links ``validation_alias`` between neighbouring fields and reports real
    settings as phantoms.
    """
    source = SETTINGS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "Settings"):
            continue
        for item in node.body:
            is_field = isinstance(item, ast.AnnAssign) and isinstance(
                item.target, ast.Name
            )
            if not is_field:
                continue
            segment = ast.get_source_segment(source, item) or ""
            match = re.search(r'validation_alias="([A-Z_]+)"', segment)
            names.add(
                match.group(1) if match else f"FLEET_AGENT_{item.target.id.upper()}"
            )
    return names


def _documented_env_names() -> set[str]:
    documented: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"#?\s*([A-Z][A-Z0-9_]+)=", line.strip())
        if match:
            documented.add(match.group(1))
    return documented


def test_env_example_documents_exactly_the_real_settings() -> None:
    """A documented key that maps to no field is a silent no-op.

    The original audit of this codebase found two of them
    (``FLEET_AGENT_ROUTER_STATE`` and ``FLEET_AGENT_MLFLOW_TRACING``): operators
    set them, they looked like configuration, and nothing read them.
    """
    real = _settings_env_names()
    documented = _documented_env_names()

    phantoms = sorted(documented - real - _UNPREFIXED_ALIASES)
    assert phantoms == [], (
        f".env.example documents keys that no setting reads: {phantoms}"
    )

    undocumented = sorted(real - documented)
    assert undocumented == [], f"settings an operator cannot discover: {undocumented}"
