"""Bounded subprocess plumbing shared by the workspace tools.

Two hard problems this module owns, separate from workspace semantics:

- A model-controlled regular expression can pin a CPython worker forever
  (``re.search`` is not interruptible), so grep matching runs in a short-lived
  ``sys.executable -I -c`` process group that the timeout can kill.
- A chatty child can fill its pipe and block the parent, so both pipes are
  drained by capped reader threads and the whole process group is killed and
  reaped once the byte cap or the deadline is hit.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Any

# Fixed matcher run with ``sys.executable -I -c``: the model-controlled
# pattern is matched inside a short-lived process group so a pathological
# regular expression is killed by the timeout instead of pinning an engine
# worker thread forever (CPython cannot interrupt a running ``re.search``).
GREP_MATCHER_SCRIPT = r"""
import json
import re
import sys

payload = json.loads(sys.stdin.read())
expression = re.compile(payload["pattern"], payload["flags"])
limit = payload["limit"]
size_cap = payload["size_cap"]
written = 0
for path, relative in payload["files"]:
    try:
        with open(path, "rb") as stream:
            raw = stream.read()
    except OSError:
        continue
    if len(raw) > size_cap or b"\x00" in raw:
        continue
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        continue
    for number, line in enumerate(text.splitlines(), start=1):
        if expression.search(line) is not None:
            print(f"{relative}:{number}: {line}")
            written += 1
            if written >= limit:
                sys.exit(0)
sys.exit(0)
"""


def read_bounded_process_output(
    process: subprocess.Popen[bytes], *, max_bytes: int, timeout: int
) -> tuple[bytes, bytes, bool, bool]:
    """Read both pipes with a hard cap and reap the process after termination."""

    if process.stdout is None or process.stderr is None:
        raise RuntimeError("workspace command pipes were not created")

    try:
        process_group_id = os.getpgid(process.pid)
    except ProcessLookupError:
        process_group_id = process.pid

    lock = threading.Lock()
    kill_lock = threading.Lock()
    stdout = bytearray()
    stderr = bytearray()
    total = 0
    truncated = False
    killed = False

    def kill_group_once() -> None:
        nonlocal killed
        with kill_lock:
            if killed:
                return
            killed = True
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def read_stream(stream: Any, target: bytearray) -> None:
        nonlocal total, truncated
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                should_kill = False
                with lock:
                    remaining = max(0, max_bytes - total)
                    if remaining:
                        target.extend(chunk[:remaining])
                        total += min(len(chunk), remaining)
                    if len(chunk) > remaining or total >= max_bytes:
                        truncated = True
                        should_kill = True
                if should_kill:
                    # Continue draining until EOF after killing so the other
                    # reader cannot block the parent on a full pipe.
                    kill_group_once()
        except (OSError, ValueError):
            # Closing a pipe after the process group is killed is expected.
            return
        finally:
            stream.close()

    readers = [
        threading.Thread(
            target=read_stream, args=(process.stdout, stdout), daemon=True
        ),
        threading.Thread(
            target=read_stream, args=(process.stderr, stderr), daemon=True
        ),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    try:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group_once()
    finally:
        if process.poll() is None:
            kill_group_once()
        # A child that inherited stdout/stderr can keep a reader alive after
        # bash exits. Give normal commands a short grace period, then close
        # those pipes and terminate the process group so this call cannot
        # retain an unbounded reader or orphan a descendant.
        for reader in readers:
            reader.join(timeout=1.0)
        if any(reader.is_alive() for reader in readers):
            kill_group_once()
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
            for reader in readers:
                reader.join(timeout=1.0)
        process.wait()

    return bytes(stdout), bytes(stderr), truncated, timed_out
