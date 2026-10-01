"""Static types and safe sets must not drift from the contracts package.

The constants in ``packages/contracts`` are the single source of truth. Some
consumers load them at runtime (error codes, termination reasons); others use
static types that cannot be derived from JSON (``Literal`` unions). This test
pins both to the canonical files so neither side can quietly diverge.
"""

from __future__ import annotations

from typing import get_args

import pytest

from app.agent.provider import MessagesFormat, ResponseFormat
from app.api.threads import _SAFE_TERMINATION_REASONS, _safe_latest_run_payload
from app.contracts import paths
from app.contracts.error_codes import ERROR_MESSAGES
from app.contracts.paths import load_contract_json
from app.contracts.termination_reasons import TERMINATION_REASONS
from app.persistence.models import Run


def test_provider_literals_match_the_contract() -> None:
    provider = load_contract_json("provider.json")
    assert isinstance(provider, dict)
    assert get_args(ResponseFormat) == tuple(provider["responseFormats"])
    assert get_args(MessagesFormat) == tuple(provider["messagesFormats"])


def test_termination_reasons_match_the_contract() -> None:
    reasons = load_contract_json("termination-reasons.json")
    assert isinstance(reasons, list)
    assert TERMINATION_REASONS == tuple(reasons)
    assert _SAFE_TERMINATION_REASONS == frozenset(reasons)


def test_error_codes_load_from_the_contract() -> None:
    codes = load_contract_json("error-codes.json")
    assert isinstance(codes, dict)
    assert dict(ERROR_MESSAGES) == codes


def test_synthesis_survives_the_safe_run_payload() -> None:
    """A run completed by synthesis keeps its reason on reload.

    ``synthesis`` is the routed program's normal completion; the safe-set
    filter must not strip it (the live stream already shows it as
    "Completed normally", and reload has to agree).
    """
    run = Run(
        id="run_synthesis",
        thread_id="thread_synthesis",
        status="completed",
        termination_reason="synthesis",
    )
    payload = _safe_latest_run_payload(run)
    assert payload is not None
    assert payload["terminationReason"] == "synthesis"


def test_missing_contracts_file_names_the_expected_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A missing contracts package must fail with the path, not a bare OSError."""
    monkeypatch.setattr(paths, "CONTRACTS_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="error-codes.json"):
        paths.load_contract_json("error-codes.json")
