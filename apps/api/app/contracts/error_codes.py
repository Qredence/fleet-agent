"""Stable public error codes.

Clients only ever see these codes + safe messages — never stack traces,
provider payloads, or internal exception strings. The mapping lives in
``packages/contracts/error-codes.json`` and is loaded at import so both
sides of the wire share one source.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, cast

from app.contracts.paths import load_contract_json

ERROR_MESSAGES: Final[Mapping[str, str]] = cast(
    "Mapping[str, str]", load_contract_json("error-codes.json")
)


def public_error(code: str | None, fallback: str = "internal_error") -> tuple[str, str]:
    """(code, safe message) — unknown codes degrade to internal_error."""
    resolved = code if code is not None and code in ERROR_MESSAGES else fallback
    return resolved, ERROR_MESSAGES[resolved]
