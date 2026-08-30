from pathlib import Path

import pytest

import app.agent.tools.workspace as workspace_module
from app.agent.tools.workspace import WorkspacePolicy, WorkspaceTools


def make_tools(
    root: Path,
    *,
    allow_write: bool = False,
    allow_bash: bool = False,
    max_read_bytes: int = 256 * 1024,
    max_output_chars: int = 12_000,
) -> WorkspaceTools:
    return WorkspaceTools(
        WorkspacePolicy(
            root=root,
            allow_write=allow_write,
            allow_bash=allow_bash,
            max_read_bytes=max_read_bytes,
            max_output_chars=max_output_chars,
        )
    )


def test_inspection_tools_are_bounded_and_skip_sensitive_paths(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text("class Agent:\n    pass\n")
    (tmp_path / ".env").write_text("SECRET=hidden\n")
    (tmp_path / ".env.local").write_text("SECRET=local\n")
    (tmp_path / ".env.example").write_text("SECRET=example\n")
    (tmp_path / "private.pem").write_text("private\n")
    (tmp_path / "id_rsa").write_text("PRIVATE KEY\n")

    tools = make_tools(tmp_path)

    assert "src/" in tools.ls()
    assert "src/agent.py" in tools.find("*.py")
    assert "src/agent.py:1: class Agent:" in tools.grep("class Agent")
    assert "SECRET=example" in tools.read(".env.example")
    with pytest.raises(ValueError, match="sensitive file"):
        tools.read(".env")
    with pytest.raises(ValueError, match="sensitive file"):
        tools.read(".env.local")
    with pytest.raises(ValueError, match="sensitive file"):
        tools.read("id_rsa")
    with pytest.raises(ValueError, match="credential/key"):
        tools.read("private.pem")


def test_paths_cannot_escape_root_or_enter_blocked_directories(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("private")

    tools = make_tools(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        tools.read("../outside.txt")
    with pytest.raises(ValueError, match="not available"):
        tools.read(".git/config")

    link = tmp_path / "outside-link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this filesystem")
    with pytest.raises(ValueError, match="escapes"):
        tools.read("outside-link")


def test_walks_skip_dependency_and_cache_directories(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("needle\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("needle\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("needle\n")

    tools = make_tools(tmp_path)

    matches = tools.grep("needle")
    assert "src/main.py:1: needle" in matches
    assert "node_modules" not in matches
    assert ".venv" not in matches
    with pytest.raises(ValueError, match="not available"):
        tools.read("node_modules/dep.js")


def test_grep_survives_catastrophic_backtracking_via_process_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A near-miss line for a nested-quantifier pattern makes re.search
    # backtrack exponentially; the process-isolated matcher must be killed
    # by the time budget instead of pinning an engine worker thread.
    (tmp_path / "evil.txt").write_text("a" * 60 + "b\n")
    monkeypatch.setattr(workspace_module, "_GREP_TIMEOUT_SECONDS", 1)
    tools = make_tools(tmp_path)

    with pytest.raises(TimeoutError, match="grep exceeded"):
        tools.grep("(a+)+$")


def test_read_line_ranges_and_grep_reject_binary_or_oversize_files(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("one\ntwo\nthree\n")
    (tmp_path / "binary.dat").write_bytes(b"one\x00two")
    (tmp_path / "large.txt").write_text("x" * 20)
    tools = make_tools(tmp_path, max_read_bytes=15)

    assert "2 | two" in tools.read("notes.txt", start_line=2, end_line=2)
    assert "binary.dat" not in tools.grep("two")
    with pytest.raises(ValueError, match="read-size"):
        tools.read("large.txt")
    with pytest.raises(ValueError, match="line range"):
        tools.read("notes.txt", end_line=1002)


def test_write_and_edit_are_disabled_by_default(tmp_path: Path):
    tools = make_tools(tmp_path)
    assert {tool.name for tool in tools.dspy_tools()} == {"ls", "find", "grep", "read"}
    with pytest.raises(PermissionError, match="write tools are disabled"):
        tools.write("new.txt", "content")


def test_write_edit_are_atomic_and_reject_ambiguous_replacements(tmp_path: Path):
    tools = make_tools(tmp_path, allow_write=True)
    assert {tool.name for tool in tools.dspy_tools()} == {
        "ls",
        "find",
        "grep",
        "read",
        "write",
        "edit",
    }
    assert "Wrote" in tools.write("nested/result.txt", "before\n")
    with pytest.raises(ValueError, match="not found"):
        tools.edit("nested/result.txt", "missing", "after")
    assert "1 replacement" in tools.edit("nested/result.txt", "before", "after")
    assert (tmp_path / "nested" / "result.txt").read_text() == "after\n"

    (tmp_path / "ambiguous.txt").write_text("same\nsame\n")
    with pytest.raises(ValueError, match="matches 2"):
        tools.edit("ambiguous.txt", "same", "new")
    tools.edit("ambiguous.txt", "same", "new", replace_all=True)
    assert (tmp_path / "ambiguous.txt").read_text() == "new\nnew\n"


def test_bash_is_opt_in_bounded_and_uses_workspace_cwd(tmp_path: Path):
    tools = make_tools(tmp_path)
    assert {tool.name for tool in tools.dspy_tools()} == {"ls", "find", "grep", "read"}
    with pytest.raises(PermissionError, match="bash tool is disabled"):
        tools.bash("pwd")

    enabled = make_tools(tmp_path, allow_bash=True)
    assert "bash" in {tool.name for tool in enabled.dspy_tools()}
    result = enabled.bash("pwd")
    assert result.startswith("exit_code=0")
    assert str(tmp_path) in result


def test_bash_uses_policy_default_and_rejects_oversized_commands(tmp_path: Path):
    tools = WorkspaceTools(
        WorkspacePolicy(
            root=tmp_path,
            allow_bash=True,
            bash_default_timeout_seconds=1,
            bash_max_timeout_seconds=2,
        )
    )

    assert tools.bash("printf ready") == "exit_code=0\nready"
    with pytest.raises(ValueError, match="command-size"):
        tools.bash("x" * 4001)


def test_bash_timeout_kills_the_process_group(tmp_path: Path):
    tools = make_tools(tmp_path, allow_bash=True)
    with pytest.raises(TimeoutError, match="exceeded"):
        tools.bash("sleep 2", timeout_seconds=1)


def test_bash_bounds_stdout_and_stderr_and_kills_the_process_group(tmp_path: Path):
    tools = make_tools(
        tmp_path,
        allow_bash=True,
        max_output_chars=256,
    )

    result = tools.bash("yes stdout & yes stderr >&2 & wait", timeout_seconds=5)

    assert len(result) <= 257  # one safe truncation marker is allowed
    assert result.startswith("exit_code=")
    assert result.endswith("…")
