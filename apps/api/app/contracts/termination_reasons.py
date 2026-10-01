"""Public run termination reasons.

The canonical list lives in ``packages/contracts/termination-reasons.json``
and is loaded at import so the API's safe-set filtering and the browser's
presentation labels cannot drift apart.
"""

from __future__ import annotations

from typing import Final, cast

from app.contracts.paths import load_contract_json

TERMINATION_REASONS: Final[tuple[str, ...]] = tuple(
    cast("list[str]", load_contract_json("termination-reasons.json"))
)
