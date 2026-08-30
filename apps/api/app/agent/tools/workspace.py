"""Bounded, policy-controlled workspace tools for Fleet Agent.

The tools deliberately use Python filesystem APIs for inspection and reserve a
shell for explicitly enabled command execution. Every path is resolved below
one configured root, and mutation is disabled by default.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dspy

from app.agent.instrumented import preview
from app.agent.tooling import create_dspy_tool

_BLOCKED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
_BLOCKED_FILENAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".netrc",
        ".pypirc",
        ".htpasswd",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "authorized_keys",
    }
)
_BLOCKED_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})
_MAX_PATTERN_CHARS = 300
_MAX_FIND_RESULTS = 500
_MAX_GREP_RESULTS = 500
_MAX_LINE_RANGE = 1000
_MAX_COMMAND_CHARS = 4000
_GREP_TIMEOUT_SECONDS = 10

# Fixed matcher run with ``sys.executable -I -c``: the model-controlled
# pattern is matched inside a short-lived process group so a pathological
# regular expression is killed by the timeout instead of pinning an engine
# worker thread forever (CPython cannot interrupt a running ``re.search``).
_GREP_MATCHER_SCRIPT = r"""
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


@dataclass(frozen=True)
class WorkspacePolicy:
    """Limits and capabilities for one run-scoped workspace tool bundle."""

    root: Path
    max_read_bytes: int = 256 * 1024
    max_write_bytes: int = 1024 * 1024
    max_output_chars: int = 12_000
    max_find_results: int = 200
    max_grep_results: int = 200
    bash_default_timeout_seconds: int = 30
    bash_max_timeout_seconds: int = 120
    allow_write: bool = False
    allow_bash: bool = False


class WorkspaceTools:
    """Typed workspace operations exposed as explicit ``dspy.Tool`` objects."""

    def __init__(self, policy: WorkspacePolicy) -> None:
        root = policy.root.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("workspace root must be an existing directory")
        if policy.max_read_bytes < 1 or policy.max_write_bytes < 1:
            raise ValueError("workspace byte limits must be positive")
        if policy.max_output_chars < 1:
            raise ValueError("workspace output limit must be positive")
        if policy.bash_default_timeout_seconds < 1:
            raise ValueError("workspace bash default timeout must be positive")
        if policy.bash_max_timeout_seconds < 1:
            raise ValueError("workspace bash maximum timeout must be positive")

        self._policy = policy
        self._root = root

    def ls(self, path: str = ".", max_entries: int = 200) -> str:
        """List files and directories directly inside a workspace directory."""
        target = self._resolve_path(path, must_exist=True)
        if not target.is_dir():
            raise ValueError("path is not a directory")

        limit = max(1, min(max_entries, _MAX_FIND_RESULTS))
        entries: list[str] = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            try:
                self._resolve_path(str(child.relative_to(self._root)), must_exist=True)
            except (OSError, ValueError):
                continue
            suffix = "/" if child.is_dir() else ""
            entries.append(f"{child.relative_to(self._root)}{suffix}")
            if len(entries) >= limit:
                break

        return self._bound_output("\n".join(entries) or "Directory is empty.")

    def find(
        self,
        pattern: str,
        path: str = ".",
        max_results: int = 100,
    ) -> str:
        """Find workspace paths matching a filename or glob pattern."""
        if not pattern or len(pattern) > _MAX_PATTERN_CHARS:
            raise ValueError("invalid find pattern")
        base = self._resolve_path(path, must_exist=True)
        if not base.is_dir():
            raise ValueError("search path is not a directory")

        limit = max(1, min(max_results, self._policy.max_find_results))
        matches: list[str] = []
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [name for name in dirs if name.lower() not in _BLOCKED_DIRS]
            for name in [*dirs, *files]:
                candidate = Path(root) / name
                try:
                    relative = candidate.relative_to(self._root)
                    self._resolve_path(str(relative), must_exist=True)
                except (OSError, ValueError):
                    continue
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(
                    str(relative), pattern
                ):
                    matches.append(str(relative))
                if len(matches) >= limit:
                    return self._bound_output("\n".join(matches))

        return self._bound_output("\n".join(matches) or "No matching paths found.")

    def grep(
        self,
        pattern: str,
        path: str = ".",
        file_glob: str = "*",
        case_sensitive: bool = True,
        max_results: int = 100,
    ) -> str:
        """Search UTF-8 workspace text files for matching lines.

        Matching runs in a process-isolated helper (see
        ``_GREP_MATCHER_SCRIPT``) so the configured time budget is enforced
        even against catastrophic-backtracking patterns.
        """
        if not pattern or len(pattern) > _MAX_PATTERN_CHARS:
            raise ValueError("invalid grep pattern")
        if not file_glob or len(file_glob) > _MAX_PATTERN_CHARS:
            raise ValueError("invalid file glob")
        try:
            # Compile once in the parent to surface invalid patterns with the
            # same error the helper would raise, before any process spawn.
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise ValueError("invalid grep regular expression") from exc

        base = self._resolve_path(path, must_exist=True)
        limit = max(
            1, min(max_results, self._policy.max_grep_results, _MAX_GREP_RESULTS)
        )
        candidates: list[tuple[str, str]] = []
        for target in [base] if base.is_file() else self._walk_files(base):
            if not fnmatch.fnmatch(target.name, file_glob):
                continue
            try:
                if target.stat().st_size > self._policy.max_read_bytes:
                    continue
            except OSError:
                continue
            candidates.append((str(target), str(target.relative_to(self._root))))
        if not candidates:
            return self._bound_output("No matching lines found.")

        payload = json.dumps(
            {
                "pattern": pattern,
                "flags": 0 if case_sensitive else re.IGNORECASE,
                "limit": limit,
                "size_cap": self._policy.max_read_bytes,
                "files": candidates,
            }
        ).encode("utf-8")
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", _GREP_MATCHER_SCRIPT],
            cwd=self._root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        if process.stdin is None:
            raise RuntimeError("workspace grep pipes were not created")
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            # The helper died before consuming its input; fall through to
            # the bounded reader, which reaps it and returns its output.
            pass
        stdout, _stderr, _truncated, timed_out = _read_bounded_process_output(
            process,
            max_bytes=self._policy.max_output_chars,
            timeout=_GREP_TIMEOUT_SECONDS,
        )
        if timed_out:
            raise TimeoutError(f"grep exceeded {_GREP_TIMEOUT_SECONDS} seconds")
        matches = stdout.decode("utf-8", errors="replace")
        return self._bound_output(matches.strip("\n") or "No matching lines found.")

    def read(
        self,
        path: str,
        start_line: int = 1,
        end_line: int = 400,
    ) -> str:
        """Read a bounded line range from a UTF-8 workspace file."""
        target = self._resolve_path(path, must_exist=True)
        if not target.is_file():
            raise ValueError("path is not a file")
        if start_line < 1:
            raise ValueError("start_line must be at least 1")
        if end_line < start_line:
            raise ValueError("end_line must be >= start_line")
        if end_line - start_line > _MAX_LINE_RANGE:
            raise ValueError("requested line range is too large")
        if target.stat().st_size > self._policy.max_read_bytes:
            raise ValueError("file exceeds the workspace read-size limit")
        try:
            text = target.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("file is not UTF-8 text") from exc

        selected = text.splitlines()[start_line - 1 : end_line]
        if not selected:
            return "No lines in requested range."
        width = len(str(start_line + len(selected) - 1))
        rendered = "\n".join(
            f"{number:>{width}} | {line}"
            for number, line in enumerate(selected, start=start_line)
        )
        return self._bound_output(rendered)

    def write(self, path: str, content: str) -> str:
        """Create or atomically overwrite a workspace text file."""
        self._require_write()
        target = self._resolve_path(path, must_exist=False)
        self._atomic_write(target, content)
        return (
            f"Wrote {len(content.encode('utf-8'))} bytes "
            f"to {target.relative_to(self._root)}."
        )

    def edit(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
    ) -> str:
        """Replace exact text in a workspace file, rejecting ambiguity by default."""
        self._require_write()
        if not old_text:
            raise ValueError("old_text must not be empty")
        target = self._resolve_path(path, must_exist=True)
        if not target.is_file():
            raise ValueError("path is not a file")
        if target.stat().st_size > self._policy.max_read_bytes:
            raise ValueError("file exceeds edit-size limit")
        raw = target.read_bytes()
        if len(raw) > self._policy.max_read_bytes:
            raise ValueError("file exceeds edit-size limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("file is not UTF-8 text") from exc

        occurrences = content.count(old_text)
        if occurrences == 0:
            raise ValueError("old_text was not found; inspect the file again")
        if occurrences > 1 and not replace_all:
            raise ValueError(
                f"old_text matches {occurrences} locations; make the edit more specific"
            )

        updated = content.replace(old_text, new_text, -1 if replace_all else 1)
        self._atomic_write(target, updated)
        return (
            f"Updated {target.relative_to(self._root)} "
            f"({occurrences} replacement{'s' if occurrences != 1 else ''})."
        )

    def bash(self, command: str, timeout_seconds: int | None = None) -> str:
        """Run a bounded shell command inside the configured workspace."""
        self._require_bash()
        if not command.strip():
            raise ValueError("command must not be empty")
        if len(command) > _MAX_COMMAND_CHARS:
            raise ValueError("command exceeds the workspace command-size limit")
        requested_timeout = (
            self._policy.bash_default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        timeout = min(max(1, requested_timeout), self._policy.bash_max_timeout_seconds)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self._root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        process = subprocess.Popen(
            ["bash", "--noprofile", "--norc", "-c", command],
            cwd=self._root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr, truncated, timed_out = _read_bounded_process_output(
            process, max_bytes=self._policy.max_output_chars, timeout=timeout
        )
        if timed_out:
            raise TimeoutError(f"command exceeded {timeout} seconds")

        output = "\n".join(
            part
            for part in (
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
            if part
        )
        rendered = f"exit_code={process.returncode}\n{output}".rstrip()
        bounded = self._bound_output(rendered)
        if truncated and not bounded.endswith("…"):
            bounded = preview(bounded.rstrip("…") + "…", self._policy.max_output_chars)
        return bounded

    def dspy_tools(self) -> list[dspy.Tool]:
        """Build the explicit tools allowed by this run's workspace policy."""
        tools = [
            create_dspy_tool(
                self.ls,
                name="ls",
                description=(
                    "List one workspace directory. Do not use shell for inspection."
                ),
                arg_descriptions={
                    "path": "Relative directory path inside the workspace.",
                    "max_entries": "Maximum number of entries to return.",
                },
            ),
            create_dspy_tool(
                self.find,
                name="find",
                description="Find workspace paths matching a filename or glob pattern.",
                arg_descriptions={
                    "pattern": "Filename or path glob, such as *.py.",
                    "path": "Relative directory in which to search.",
                    "max_results": "Maximum number of matching paths.",
                },
            ),
            create_dspy_tool(
                self.grep,
                name="grep",
                description="Search workspace UTF-8 text files for matching lines.",
                arg_descriptions={
                    "pattern": "Regular expression to search for.",
                    "path": "Relative file or directory to search.",
                    "file_glob": "Filename glob used to limit searched files.",
                    "case_sensitive": (
                        "Whether the regular expression is case-sensitive."
                    ),
                    "max_results": "Maximum number of matching lines.",
                },
            ),
            create_dspy_tool(
                self.read,
                name="read",
                description=(
                    "Read an exact bounded line range from a known workspace file."
                ),
                arg_descriptions={
                    "path": "Relative UTF-8 file path inside the workspace.",
                    "start_line": "First 1-based line to return.",
                    "end_line": "Last 1-based line to return.",
                },
            ),
        ]
        if self._policy.allow_write:
            tools.extend(
                [
                    create_dspy_tool(
                        self.write,
                        name="write",
                        description=(
                            "Create or atomically replace a workspace text file."
                        ),
                        arg_descriptions={
                            "path": "Relative target file path inside the workspace.",
                            "content": "Complete UTF-8 file content.",
                        },
                    ),
                    create_dspy_tool(
                        self.edit,
                        name="edit",
                        description=(
                            "Replace exact text in a workspace file; ambiguous "
                            "matches fail safely."
                        ),
                        arg_descriptions={
                            "path": "Relative UTF-8 file path inside the workspace.",
                            "old_text": "Exact text to replace.",
                            "new_text": "Replacement text.",
                            "replace_all": "Explicitly permit replacing every match.",
                        },
                    ),
                ]
            )
        if self._policy.allow_bash:
            tools.append(
                create_dspy_tool(
                    self.bash,
                    name="bash",
                    description=(
                        "Run a bounded command with a minimal environment in "
                        "the workspace."
                    ),
                    arg_descriptions={
                        "command": (
                            "Command to run; use read, find, grep, or ls for "
                            "ordinary inspection."
                        ),
                        "timeout_seconds": (
                            "Maximum command duration, capped by server policy."
                        ),
                    },
                )
            )
        return tools

    def _resolve_path(self, path: str, *, must_exist: bool) -> Path:
        raw = Path(path)
        if raw.is_absolute():
            raise ValueError("absolute paths are not allowed")
        try:
            candidate = (self._root / raw).resolve(strict=must_exist)
        except FileNotFoundError as exc:
            raise ValueError("path does not exist") from exc
        if not candidate.is_relative_to(self._root):
            raise ValueError("path escapes the workspace root")

        relative = candidate.relative_to(self._root)
        if any(part.lower() in _BLOCKED_DIRS for part in relative.parts):
            raise ValueError("path is not available to workspace tools")
        name = candidate.name.lower()
        if name == ".env.example":
            return candidate
        # Block every dotenv variant (.env.local, .env.production, ...);
        # only the documented .env.example template stays readable.
        if name.startswith(".env") or name in _BLOCKED_FILENAMES:
            raise ValueError("sensitive file is not available")
        if candidate.suffix.lower() in _BLOCKED_SUFFIXES:
            raise ValueError("credential/key file is not available")
        return candidate

    def _walk_files(self, base: Path) -> Iterable[Path]:
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [name for name in dirs if name.lower() not in _BLOCKED_DIRS]
            for name in files:
                candidate = Path(root) / name
                try:
                    relative = candidate.relative_to(self._root)
                    resolved = self._resolve_path(str(relative), must_exist=True)
                except (OSError, ValueError):
                    continue
                if resolved.is_file():
                    yield resolved

    def _atomic_write(self, target: Path, content: str) -> None:
        encoded = content.encode("utf-8")
        if len(encoded) > self._policy.max_write_bytes:
            raise ValueError("content exceeds write-size limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _bound_output(self, value: str) -> str:
        return preview(value, limit=self._policy.max_output_chars)

    def _require_write(self) -> None:
        if not self._policy.allow_write:
            raise PermissionError("workspace write tools are disabled")

    def _require_bash(self) -> None:
        if not self._policy.allow_bash:
            raise PermissionError("workspace bash tool is disabled")


def _read_bounded_process_output(
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
