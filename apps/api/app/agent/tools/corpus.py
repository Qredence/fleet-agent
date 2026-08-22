"""Small bundled documentation corpus searched by the search_docs tool.

Keeping the corpus in-repo makes the mock and the engine deterministic — no
network in normal CI. Real retrieval swaps in behind the same tool boundary
in PR 8 (sources).
"""

CORPUS: list[dict[str, str | None]] = [
    {
        "id": "doc-agui-events",
        "title": "AG-UI event protocol",
        "uri": "https://docs.ag-ui.com/sdk/python/core/events",
        "source_type": "web",
        "text": (
            "AG-UI streams typed events over SSE: lifecycle (RUN_STARTED, "
            "RUN_FINISHED, RUN_ERROR), text (TEXT_MESSAGE_*), tool calls "
            "(TOOL_CALL_*), and state (STATE_SNAPSHOT, STATE_DELTA). State "
            "deltas are RFC 6902 JSON Patch applied to the client snapshot; "
            "the snapshot must arrive before any delta."
        ),
    },
    {
        "id": "doc-assistant-ui-state",
        "title": "assistant-ui agent state",
        "uri": "https://www.assistant-ui.com/docs/runtimes/ag-ui/agent-state",
        "source_type": "web",
        "text": (
            "useAgUiState mirrors state the AG-UI agent owns and re-renders as "
            "STATE_SNAPSHOT and STATE_DELTA events arrive. useAuiState reads "
            "assistant-ui client state such as messages and thread.isRunning. "
            "showThinking=false hides THINKING_*/REASONING_* events."
        ),
    },
    {
        "id": "doc-workspace-layout",
        "title": "Workspace layout",
        "uri": None,
        "source_type": "document",
        "text": (
            "Three panes: projects/threads sidebar left, assistant-ui "
            "conversation center, process panel right. Below 1200px the process "
            "panel becomes a sheet; below 768px both side panels become sheets."
        ),
    },
    {
        "id": "doc-cot-boundary",
        "title": "Chain-of-thought boundary",
        "uri": None,
        "source_type": "document",
        "text": (
            "The process panel renders the intentional public trace "
            "(AgentWorkspaceState): steps, public summaries, tool calls, "
            "sources, artifacts, decisions, caveats. Raw next_thought, prompts, "
            "and provider payloads never leave the backend."
        ),
    },
    {
        "id": "doc-reactv2-termination",
        "title": "DSPy ReActV2 termination",
        "uri": "https://dspy.ai/diving-deeper/react/",
        "source_type": "web",
        "text": (
            "ReActV2 finishes via the internal submit tool with typed outputs, "
            "or falls back to a forced submission on max_iters, empty tool "
            "calls, parse errors, or context window exhaustion. A failed forced "
            "submission returns history and termination_reason without the "
            "declared output fields."
        ),
    },
    {
        "id": "doc-fixture-streams",
        "title": "Fixture streams",
        "uri": None,
        "source_type": "document",
        "text": (
            "Canonical NDJSON fixtures (successful, tool-error recovery, "
            "forced-submit) replay deterministically through POST /api/agent. "
            "They are the regression contract for the transport and panel."
        ),
    },
    {
        "id": "doc-contracts-workflow",
        "title": "Contracts workflow",
        "uri": None,
        "source_type": "document",
        "text": (
            "packages/contracts holds the AgentWorkspaceState JSON Schema. "
            "Python models and TypeScript types are generated from it; "
            "freshness tests fail when generated files go stale."
        ),
    },
]
