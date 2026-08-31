"""Single import seam for the DSPy symbols the approval loop depends on.

``approval.py`` re-implements the ReActV2 forward loop to inject the
pause/resume approval seam, and that loop depends on a handful of private
(underscore-prefixed) helpers in ``dspy.predict.react_v2``. This module is
the ONE place those symbols are imported, guarded by an import-time version
check, so dependency drift fails loudly at startup with an actionable
message instead of surfacing as a silent approval bug mid-run.

Rules:
- Never import private DSPy symbols anywhere else in the app.
- ``tests/test_dspy_compat.py`` pins the behavior of every re-exported
  helper against the installed DSPy version; update it (and the pin) in the
  same change that bumps DSPy.
"""

from __future__ import annotations

import dspy
from dspy.adapters.types.tool import ToolCallResults, ToolCalls
from dspy.utils.exceptions import (
    AdapterParseError,
    ContextWindowExceededError,
    format_error_for_lm,
)

# The lockfile pins dspy exactly (``dspy==3.3.1``); anything else is untested
# drift for the private helpers below.
EXPECTED_DSPY_VERSION = "3.3.1"

if dspy.__version__ != EXPECTED_DSPY_VERSION:  # pragma: no cover - import-time guard
    raise RuntimeError(
        f"dspy {dspy.__version__!r} does not match the approved compatibility "
        f"version {EXPECTED_DSPY_VERSION!r}. The approval loop depends on "
        "private dspy.predict.react_v2 helpers: re-run the contract tests in "
        "tests/test_dspy_compat.py, verify ApprovalAwareReActV2 parity, and "
        "update this pin in the same change before deploying."
    )

from dspy.predict.react_v2 import (  # noqa: E402  (guard must precede the import)
    _append_history_event as append_history_event,
)
from dspy.predict.react_v2 import (  # noqa: E402
    _coerce_history as coerce_history,
)
from dspy.predict.react_v2 import (  # noqa: E402
    _coerce_tool_calls as coerce_tool_calls,
)
from dspy.predict.react_v2 import (  # noqa: E402
    _ensure_tool_call_ids as ensure_tool_call_ids,
)

__all__ = [
    "AdapterParseError",
    "ContextWindowExceededError",
    "EXPECTED_DSPY_VERSION",
    "ToolCallResults",
    "ToolCalls",
    "append_history_event",
    "coerce_history",
    "coerce_tool_calls",
    "ensure_tool_call_ids",
    "format_error_for_lm",
]
