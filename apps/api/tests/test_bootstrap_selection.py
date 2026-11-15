"""Unit tests for pure bootstrap latest-run selection."""

from types import SimpleNamespace

from app.persistence.bootstrap_selection import select_latest_bootstrap_run


def _msg(message_id: str, parent_message_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        message_id=message_id, parent_message_id=parent_message_id
    )


def _run(
    run_id: str,
    *,
    input_message_id: str | None = None,
    output_message_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        input_message_id=input_message_id,
        output_message_id=output_message_id,
    )


def _state(
    *,
    run_id: str | None = None,
    head_message_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(run_id=run_id, head_message_id=head_message_id)


def test_null_head_prefers_state_run_then_first_candidate() -> None:
    state_run = _run("run-state")
    other = _run("run-other")
    assert (
        select_latest_bootstrap_run(
            message_rows=[],
            candidates=[other, state_run],
            state_row=_state(run_id="run-state"),
            active_head_message_id=None,
        )
        is state_run
    )
    assert (
        select_latest_bootstrap_run(
            message_rows=[],
            candidates=[other],
            state_row=None,
            active_head_message_id=None,
        )
        is other
    )


def test_branch_latest_at_head_wins() -> None:
    messages = [
        _msg("user-1"),
        _msg("assistant-1", "user-1"),
    ]
    branch_run = _run(
        "run-branch",
        input_message_id="user-1",
        output_message_id="assistant-1",
    )
    state_run = _run(
        "run-state",
        input_message_id="user-1",
        output_message_id="assistant-old",
    )
    assert (
        select_latest_bootstrap_run(
            message_rows=messages,
            candidates=[branch_run, state_run],
            state_row=_state(run_id="run-state", head_message_id="assistant-old"),
            active_head_message_id="assistant-1",
        )
        is branch_run
    )


def test_exact_state_at_head_prefers_state_run() -> None:
    messages = [
        _msg("user-1"),
        _msg("assistant-1", "user-1"),
    ]
    # On the branch but not at the active head (no output yet).
    branch_run = _run(
        "run-branch",
        input_message_id="user-1",
        output_message_id=None,
    )
    state_run = _run(
        "run-state",
        input_message_id="user-1",
        output_message_id="assistant-1",
    )
    # Exact state at the active head and branch_latest not at head → state_run.
    assert (
        select_latest_bootstrap_run(
            message_rows=messages,
            candidates=[branch_run, state_run],
            state_row=_state(run_id="run-state", head_message_id="assistant-1"),
            active_head_message_id="assistant-1",
        )
        is state_run
    )


def test_tools_head_counts_as_exact_state() -> None:
    messages = [_msg("user-1"), _msg("msg-tools-run-state", "user-1")]
    state_run = _run(
        "run-state",
        input_message_id="user-1",
        output_message_id=None,
    )
    other = _run("run-other", input_message_id="user-1", output_message_id=None)
    assert (
        select_latest_bootstrap_run(
            message_rows=messages,
            candidates=[other, state_run],
            state_row=_state(run_id="run-state", head_message_id="user-1"),
            active_head_message_id="msg-tools-run-state",
        )
        is state_run
    )


def test_empty_candidates_returns_none() -> None:
    assert (
        select_latest_bootstrap_run(
            message_rows=[],
            candidates=[],
            state_row=None,
            active_head_message_id=None,
        )
        is None
    )
