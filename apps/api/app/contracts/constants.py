"""Loaded constants from ``packages/contracts``.

``packages/contracts`` is the single source of truth for the public protocol,
but it is an npm workspace package, not an installed Python distribution, so
consumers resolve it relative to this module:
``app/contracts -> app -> api -> apps -> repository root``.

The three constant families load here so the API and the browser cannot drift
apart: stable error codes, canonical termination reasons, and the paths that
resolve them. Servers fail fast at import when the package is missing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final, cast

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_DIR = REPO_ROOT / "packages" / "contracts"


def load_contract_json(name: str) -> object:
    """Read one contracts JSON file, failing with the expected path.

    The error must name the expected path so a misdeployed layout is
    diagnosable.
    """
    path = CONTRACTS_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"packages/contracts is required at runtime; expected {path}"
        ) from exc


ERROR_MESSAGES: Final[Mapping[str, str]] = cast(
    "Mapping[str, str]", load_contract_json("error-codes.json")
)
"""Stable public codes + safe messages. Never stack traces or provider text."""


def public_error(code: str | None, fallback: str = "internal_error") -> tuple[str, str]:
    """(code, safe message) — unknown codes degrade to internal_error."""
    resolved = code if code is not None and code in ERROR_MESSAGES else fallback
    return resolved, ERROR_MESSAGES[resolved]


TERMINATION_REASONS: Final[tuple[str, ...]] = tuple(
    cast("list[str]", load_contract_json("termination-reasons.json"))
)
"""Canonical public run termination reasons."""
