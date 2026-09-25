"""One branch walk, shared by the DSPy state and history lookups.

A thread is a tree: every message points at its parent, and a run's continuation
state (and its DSPy history) is stored against the message that produced it. To
continue a branch you walk from a head message to the nearest ancestor that has a
stored anchor, and a run's tool turn keys off its own message ids.

Both lookups need exactly that walk. Keeping one copy means the alias rule for a
run's tool turn - and the cycle guard - cannot drift between them.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Message, Run


class Anchor(Protocol):
    """A row stored against the message that produced it."""

    thread_id: str
    head_message_id: str | None


async def nearest_anchor[AnchorT: Anchor](
    session: AsyncSession,
    *,
    thread_id: str,
    head_message_id: str | None,
    model: type[AnchorT],
) -> AnchorT | None:
    """Return the nearest ``model`` row on the branch ending at ``head_message_id``.

    Rows keyed by a run's *input* message resolve to the same anchor as that
    run's output, and ``msg-tools-{run_id}`` is accepted as an alias for it, so a
    follow-up lookup from a run's own tool turn finds the same stored state.
    """
    # SQLAlchemy types the column accessor on the mapped class itself; the
    # Protocol describes the mapped attributes, so the clause needs the ignore.
    rows = await session.execute(
        select(model).where(model.thread_id == thread_id)  # type: ignore[arg-type]
    )
    anchors: dict[str | None, AnchorT] = {
        row.head_message_id: row for row in rows.scalars()
    }

    message_rows = await session.execute(
        select(Message.message_id, Message.parent_message_id).where(
            Message.thread_id == thread_id
        )
    )
    parents = {message_id: parent for message_id, parent in message_rows}

    run_rows = await session.execute(
        select(Run.id, Run.input_message_id, Run.output_message_id).where(
            Run.thread_id == thread_id
        )
    )
    for run_id, run_input, run_output in run_rows.all():
        anchor = (
            anchors.get(run_output) if run_output is not None else None
        ) or anchors.get(f"msg-{run_id}")
        if anchor is not None:
            anchors[f"msg-tools-{run_id}"] = anchor
            if run_input and run_input not in anchors:
                anchors[run_input] = anchor

    current = head_message_id
    seen: set[str] = set()
    while current is not None and current not in seen:
        if current in anchors:
            return anchors[current]
        if current.startswith("msg-tools-"):
            alternative = current.replace("msg-tools-", "msg-", 1)
            if alternative in anchors:
                return anchors[alternative]
        seen.add(current)
        current = parents.get(current)
    return anchors.get(None)
