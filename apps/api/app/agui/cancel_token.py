"""Cooperative cancellation for live runs.

The coordinator sets the token when the client disconnects (or the run is
cancelled); instrumented tools check it BEFORE doing work, which is the
guarantee "no new tool starts after cancellation is observed". A ReActV2
iteration already inside a provider call may finish — that is the documented
limit — but nothing new starts, and late bus events are never emitted.
"""

import threading


class RunCancelledError(Exception):
    """Raised by instrumented tools when their run was cancelled."""


class RunCancelToken:
    __slots__ = ("_flag",)

    def __init__(self) -> None:
        self._flag = threading.Event()

    def cancel(self) -> None:
        self._flag.set()

    @property
    def cancelled(self) -> bool:
        return self._flag.is_set()

    def check(self) -> None:
        if self._flag.is_set():
            raise RunCancelledError("run cancelled")
