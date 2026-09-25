"""Offline code-agent eval: one fixture repo, one task, pass/fail by real tests.

The task is deliberately tiny (a one-line arithmetic bug): v1 measures the LOOP
(plan -> change -> verify), not deep reasoning. Harder tasks arrive as more
fixtures, not as a bigger harness.

Contract, mirroring the routing suite:
- exit 0 only if the suite is green after the run AND was red before it (a task
  whose suite already passes proves nothing);
- no provider calls happen until after validation; no database is touched;
- the agent's shell and file writes are confined to a temp copy of the fixture,
  and the model-directed commands only ever run there.

MLflow logging is intentionally absent in v1: a single binary task is reported
on stdout with an exit code. It joins the tracked suites when there is more
than one task worth trending.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import dspy

from app.agent.code import CodeAgent, VerifyResult, build_code_agent
from app.agent.tools.workspace import WorkspacePolicy, WorkspaceTools

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "code"
TASK = "Fix calc.add so the test suite passes. Run the tests before finishing."
TEST_TARGET = "test_calc.py"
TEST_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class CodeScore:
    """Whether the suite is green after the run, and what the runner saw."""

    passed: bool
    summary: str


def run_pytest(
    cwd: Path, target: str = TEST_TARGET, timeout_s: float = TEST_TIMEOUT_S
) -> VerifyResult:
    """Run the fixture suite in ``cwd``. Bounded; never raises."""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", target, "-q"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(passed=False, summary=f"timed out after {timeout_s}s")
    except Exception as exc:
        return VerifyResult(passed=False, summary=f"test runner failed: {exc}")
    tail = "\n".join(completed.stdout.strip().splitlines()[-3:])
    return VerifyResult(passed=completed.returncode == 0, summary=tail or "(no output)")


def validate_code_fixture() -> list[str]:
    """Check the task is sound without needing a provider."""
    problems: list[str] = []
    for name in ("calc.py", "test_calc.py"):
        if not (FIXTURE_DIR / name).is_file():
            problems.append(f"fixture file missing: {name}")
    if problems:
        return problems
    with tempfile.TemporaryDirectory(prefix="code-eval-validate-") as tmp:
        workspace = Path(tmp) / "code"
        shutil.copytree(FIXTURE_DIR, workspace)
        before = run_pytest(workspace)
    if before.passed:
        problems.append("fixture suite already passes pre-fix; the task is vacuous")
    return problems


def run_code_task(
    *,
    lm: dspy.BaseLM,
    max_attempts: int = 3,
    max_iters: int = 6,
) -> CodeScore:
    """Copy the fixture, run the code agent against the copy, score the suite."""
    with tempfile.TemporaryDirectory(prefix="code-eval-") as tmp:
        workspace = Path(tmp) / "code"
        shutil.copytree(FIXTURE_DIR, workspace)
        tools = WorkspaceTools(
            WorkspacePolicy(
                root=workspace,
                allow_write=True,
                allow_bash=True,
            )
        ).dspy_tools()
        agent: CodeAgent = build_code_agent(
            tools,
            test_command=lambda: run_pytest(workspace),
            max_attempts=max_attempts,
            max_iters=max_iters,
        )
        adapter = dspy.JSONAdapter(use_native_function_calling=True)
        with dspy.context(lm=lm, adapter=adapter):
            agent(user_request=TASK)
        after = run_pytest(workspace)
    return CodeScore(passed=after.passed, summary=after.summary)
