"""Bounded, always-parseable evidence JSON for the synthesis predictor.

Both DSPy programs hand their synthesis predictor an ``evidence_json`` input
field: a JSON document of bounded tool observations. The field is typed
``str``, so the model parses it — which means the renderer must never hand the
model a truncated document.

The previous renderer sliced the serialized payload at a fixed character
budget (``text[:max_chars - 1] + "…"``). Any run whose evidence exceeded the
budget — the common case once two or three tool results accumulate — reached
the synthesizer as unparseable JSON, so the model answered from a broken
fragment instead of the evidence the loop had gathered.

``bounded_json`` spends the same budget on valid JSON instead: entries are
kept in order, and the entry that overflows is shortened to exactly the room
that is left. The synthesizer therefore sees the largest parseable prefix of
the evidence, with the tool name and error flag of every retained entry
intact.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_MAX_CHARS = 8000
"""Default character budget for one evidence document."""

_ELLIPSIS = "…"

# Explicit separators so the budget accounting below is exact: the array
# separator is one character, not ``json.dumps``' default ", ".
_SEPARATORS = (",", ":")


def bounded_json(
    items: Sequence[Mapping[str, Any]],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Serialize evidence entries as JSON within ``max_chars``, always valid.

    Entries are kept in document order until the budget runs out. The entry
    that overflows is not dropped while there is room for it: its strings are
    shortened to the largest prefix that still fits, so a single oversized
    tool result fills the budget instead of being cut to a fraction of it.
    """
    if max_chars < 4:
        raise ValueError("max_chars must leave room for a JSON array")

    separator = len(_SEPARATORS[0])
    kept: list[Mapping[str, Any]] = []
    used = 2  # the enclosing "[]"
    for item in items:
        cost = len(_dump([item])) - 2 + (separator if kept else 0)
        if used + cost <= max_chars:
            kept.append(item)
            used += cost
            continue
        room = max_chars - used - (separator if kept else 0)
        fitted = _fit_entry(item, budget=room)
        if fitted is not None:
            kept.append(fitted)
        break

    return _dump(kept)


def cap_strings(value: Any, limit: int) -> Any:
    """Truncate every string inside a JSON-ready value to ``limit`` characters.

    Truncating before serialization is what keeps the document parseable: the
    result is still a JSON string value, just a shorter one.
    """
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + _ELLIPSIS
    if isinstance(value, Mapping):
        return {key: cap_strings(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [cap_strings(item, limit) for item in value]
    return value


def _fit_entry(item: Mapping[str, Any], *, budget: int) -> Mapping[str, Any] | None:
    """Shorten one entry's strings to the largest prefix that fits ``budget``.

    Serialized length grows monotonically with the string limit, so a binary
    search finds the most evidence the remaining room can hold. ``None`` means
    even a one-character limit does not fit, and the entry is dropped.
    """
    low, high = 1, max(budget, 1)
    best: Mapping[str, Any] | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = cap_strings(item, middle)
        # _dump wraps the candidate in a one-element array; ``budget`` is the
        # room for the entry alone, so discount those two brackets. Without
        # this the entry stops two characters short of the budget.
        if len(_dump([candidate])) - 2 <= budget:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=_SEPARATORS)
