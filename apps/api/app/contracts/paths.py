"""Filesystem anchors for the shared contracts package.

``packages/contracts`` is the single source of truth for the public protocol,
but it is an npm workspace package, not an installed Python distribution, so
consumers resolve it relative to this module:
``app/contracts -> app -> api -> apps -> repository root``.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_DIR = REPO_ROOT / "packages" / "contracts"


def load_contract_json(name: str) -> object:
    """Read one contracts JSON file, failing with the expected path.

    The server deliberately fails fast at import when the contracts package is
    missing (no silent fallback), but the error must name the expected path so
    a misdeployed layout is diagnosable.
    """
    path = CONTRACTS_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"packages/contracts is required at runtime; expected {path}"
        ) from exc
