"""Pure selection of the latest bootstrap run for a thread head.

Kept out of ``repositories.py`` so that module stays typed-query only.
"""

from __future__ import annotations

from typing import Protocol


class BootstrapMessage(Protocol):
    message_id: str
    parent_message_id: str | None


class BootstrapRun(Protocol):
    id: str
    input_message_id: str | None
    output_message_id: str | None


class BootstrapStateRow(Protocol):
    run_id: str | None
    head_message_id: str | None


def select_latest_bootstrap_run[TRun: BootstrapRun](
    *,
    message_rows: list[BootstrapMessage],
    candidates: list[TRun],
    state_row: BootstrapStateRow | None,
    active_head_message_id: str | None,
) -> TRun | None:
    """Choose the run that should seed bootstrap ``latestRun``.

    ``candidates`` must already be ordered newest-first
    (``reserved_at`` desc, then ``id`` desc).
    """
    state_run = next(
        (
            candidate
            for candidate in candidates
            if state_row is not None and candidate.id == state_row.run_id
        ),
        None,
    )
    if active_head_message_id is None:
        return state_run or (candidates[0] if candidates else None)

    parents = {row.message_id: row.parent_message_id for row in message_rows}
    branch_ids: set[str] = set()
    current_id: str | None = active_head_message_id
    while current_id is not None and current_id not in branch_ids:
        branch_ids.add(current_id)
        current_id = parents.get(current_id)

    branch_latest = next(
        (
            candidate
            for candidate in candidates
            if (
                candidate.output_message_id in branch_ids
                if candidate.output_message_id is not None
                else candidate.input_message_id in branch_ids
            )
        ),
        None,
    )
    exact_state = state_row is not None and (
        state_row.head_message_id == active_head_message_id
        or (
            state_row.run_id is not None
            and active_head_message_id == f"msg-tools-{state_row.run_id}"
        )
    )
    branch_latest_is_at_head = branch_latest is not None and (
        branch_latest.output_message_id == active_head_message_id
        or (
            branch_latest.output_message_id is None
            and branch_latest.input_message_id == active_head_message_id
        )
    )
    if branch_latest_is_at_head or not exact_state:
        return (
            branch_latest or state_run or (candidates[0] if candidates else None)
        )
    return state_run or branch_latest or (candidates[0] if candidates else None)
