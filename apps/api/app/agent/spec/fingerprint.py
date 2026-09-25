"""Canonical fingerprint of one agent spec.

The fingerprint covers the declarative structure: agent name, signature fields
and their types, module topology, and tool/reward names. Prompt text is not
hashed, because instructions are exactly what an optimizer rewrites. The
fingerprint exists because DSPy's ``Signature.load_state`` matches fields
POSITIONALLY and silently accepts a shorter state; state is therefore only
accepted when it was written for this structure.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.agent.spec.schema import AgentSpec, fail

HASH_PREFIX = "sha256:"


def canonical_spec(spec: AgentSpec) -> str:
    """Return the canonical JSON text of the spec's declarative structure."""
    dump = spec.model_dump(mode="json")
    return json.dumps(dump, sort_keys=True, separators=(",", ":"))


def structure_hash(spec: AgentSpec) -> str:
    """Return the stable ``sha256:<hex>`` fingerprint of one spec."""
    return HASH_PREFIX + hashlib.sha256(canonical_spec(spec).encode()).hexdigest()


def verify_state(state: dict[str, Any], expected: str) -> None:
    """Refuse a state that was not written for this structure."""
    found = state.get("structure_hash")
    if found != expected:
        fail(f"state was written for a different spec: {found!r} != {expected!r}")
    metadata = state.get("metadata")
    if not isinstance(metadata, dict) or "dependency_versions" not in metadata:
        fail("state is missing metadata.dependency_versions")
