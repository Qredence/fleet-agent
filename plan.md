# Detailed implementation plan

## 1. Target architecture

Build the application as a **three-pane agent workspace**:

```text
┌──────────────────┬───────────────────────────────┬────────────────────────┐
│ Projects/Threads │ Main conversation             │ Process panel          │
│                  │                               │                        │
│ Project A        │ assistant-ui Thread           │ Activity               │
│  ├ Thread 1      │                               │ Sources                │
│  ├ Thread 2      │ User-facing responses         │ Artifacts              │
│  └ New thread    │ Concise progress indicators   │ Decisions              │
│                  │                               │ Tool details           │
└──────────────────┴───────────────────────────────┴────────────────────────┘
```

Use two separate presentation channels:

1. **Conversation channel:** AG-UI text, message, and lifecycle events rendered by assistant-ui.
2. **Process channel:** AG-UI agent state rendered by a custom `ProcessPanel`.

The right panel should not display raw DSPy `next_thought` values or unrestricted model chain-of-thought. It should display an intentional, user-safe trace containing:

* Current phase
* Completed and active steps
* Tool calls
* Sources
* Artifacts
* Alternatives considered
* Decisions and concise rationales
* Caveats
* Duration and token usage

assistant-ui’s AG-UI runtime already owns the parsing and reconstruction of AG-UI messages from an `HttpAgent`. Its agent-state hooks are explicitly intended for rendering agent-owned state beside the conversation. ([assistant-ui][1])

## 2. Recommended technology stack

### Frontend

* React 19
* TypeScript
* Vite and React Router for a standalone frontend
* shadcn/ui using Base UI
* assistant-ui
* `@assistant-ui/react-ag-ui`
* `@ag-ui/client`
* Zod for application-level validation
* TanStack Query for REST resources such as projects, threads, sources, and artifacts
* Small Zustand store only for workspace UI state:

  * Open panels
  * Panel width
  * Active tab
  * Active project
  * Active thread

Vite is the simpler default because FastAPI already owns the server layer. Retain Next.js instead when the existing application is already built on Next.js.

assistant-ui currently provides Base UI-compatible registry components through a style-aware shadcn registry, while its headless React package behaves the same under Base UI and Radix. ([assistant-ui][2])

### Backend

* Python
* FastAPI
* DSPy
* `ag-ui-protocol`
* Pydantic and `pydantic-settings`
* `orjson`
* PostgreSQL
* SQLAlchemy 2 and Alembic
* Object storage for artifacts
* Redis later, when multiple backend workers or resumable runs are required

### Transport

Use **HTTP POST + SSE through AG-UI**.

Do not introduce:

* A custom SSE protocol
* Vercel AI SDK
* CopilotKit
* WebSockets
* Direct DSPy stream objects in the frontend

The AG-UI Python SDK provides typed events and an `EventEncoder` that emits the expected SSE representation. ([Agent User Interaction Protocol][3])

---

# 3. State ownership

Keep three state layers strictly separated.

## 3.1 Application state

Owned by React, the URL, TanStack Query, or Zustand:

```text
activeProjectId
activeThreadId
processPanelOpen
processPanelWidth
processPanelTab
sidebarCollapsed
theme
authenticatedUser
```

This state is not part of the agent protocol.

## 3.2 Conversation state

Owned by assistant-ui:

```text
messages
composer
attachments
isRunning
message status
regeneration
editing
cancellation
```

Use `useAuiState` for this layer.

## 3.3 Agent workspace state

Owned by the backend and synchronized through AG-UI:

```text
current process phase
steps
decisions
tool executions
sources
artifacts
run metrics
termination information
```

Use `useAgUiState<AgentWorkspaceState>()` for this layer. `STATE_SNAPSHOT` replaces the complete state and `STATE_DELTA` applies JSON Patch updates while the run is active. ([assistant-ui][4])

This gives the panel a direct data model:

```text
FastAPI
    │
    ├── STATE_SNAPSHOT
    ├── STATE_DELTA
    └── STATE_DELTA
           │
           ▼
useAgUiState<AgentWorkspaceState>()
           │
           ▼
ProcessPanel
```

Do not reconstruct this state by scanning assistant messages or parsing `dspy.History`.

---

# 4. Public trace contract

Create a stable application contract that is independent of DSPy.

```ts
export interface AgentWorkspaceState {
  schemaVersion: 1;

  threadId: string;

  run: {
    id: string;
    status:
      | "idle"
      | "queued"
      | "running"
      | "completed"
      | "failed"
      | "cancelled";

    startedAt?: string;
    finishedAt?: string;
    activeStepId?: string;
    terminationReason?: string;
    errorCode?: string;
  };

  steps: ProcessStep[];
  decisions: ProcessDecision[];
  toolCalls: ToolExecution[];
  sources: AgentSource[];
  artifacts: AgentArtifact[];

  metrics: {
    durationMs?: number;
    inputTokens?: number;
    outputTokens?: number;
    totalTokens?: number;
    toolCallCount: number;
    modelCallCount?: number;
  };
}

export interface ProcessStep {
  id: string;
  parentId?: string;

  phase:
    | "understanding"
    | "planning"
    | "research"
    | "analysis"
    | "critique"
    | "synthesis";

  title: string;

  /**
   * Explicitly written for the user.
   * Never populate this with raw model chain-of-thought.
   */
  publicSummary?: string;

  status: "pending" | "running" | "completed" | "failed";

  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;

  toolCallIds: string[];
  sourceIds: string[];
  artifactIds: string[];
}

export interface ProcessDecision {
  id: string;
  title: string;
  alternatives: string[];
  selected?: string;
  publicRationale?: string;
  status: "considering" | "accepted" | "rejected";
}

export interface ToolExecution {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed";

  inputPreview?: string;
  outputPreview?: string;
  errorMessage?: string;

  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
}

export interface AgentSource {
  id: string;
  title: string;
  sourceType: "web" | "document" | "repository" | "database" | "other";
  uri?: string;
  excerpt?: string;
  toolCallId?: string;
}

export interface AgentArtifact {
  id: string;
  name: string;
  mediaType: string;
  sizeBytes?: number;
  downloadUrl?: string;
  status: "generating" | "ready" | "failed";
}
```

Generate this contract from a checked-in JSON Schema or from backend Pydantic models. Do not maintain unrelated handwritten Python and TypeScript definitions.

Every state payload must carry a `schemaVersion`. Any breaking shape change increments it.

---

# 5. AG-UI event mapping

Use the following mapping:

| AG-UI event            | Application behavior                                       |
| ---------------------- | ---------------------------------------------------------- |
| `RUN_STARTED`          | Mark assistant-ui thread as running                        |
| `STATE_SNAPSHOT`       | Initialize the right-panel state                           |
| `STATE_DELTA`          | Update the right panel incrementally                       |
| `TOOL_CALL_START`      | Register a tool call in assistant-ui and the process panel |
| `TOOL_CALL_ARGS`       | Stream or attach sanitized arguments                       |
| `TOOL_CALL_END`        | Finish argument streaming                                  |
| `TOOL_CALL_RESULT`     | Record the result and status                               |
| `TEXT_MESSAGE_START`   | Begin the final assistant response                         |
| `TEXT_MESSAGE_CONTENT` | Append final response content                              |
| `TEXT_MESSAGE_END`     | Complete the response                                      |
| `CUSTOM`               | Message-scoped application data only                       |
| `RUN_FINISHED`         | Finalize run state and metrics                             |
| `RUN_ERROR`            | Mark the run and assistant message as failed               |

AG-UI defines lifecycle, tool-call, state, text, step, and custom events; state deltas use JSON Patch. ([Agent User Interaction Protocol][5])

### Use `CUSTOM` sparingly

Use `CUSTOM` events for data that belongs to a particular assistant response, such as:

* An inline artifact card
* A recommendation card
* A source summary
* A user approval request

assistant-ui stores custom events as named data parts on the in-flight assistant message. They are message-scoped, whereas `STATE_SNAPSHOT` and `STATE_DELTA` are better suited to the persistent side panel. ([assistant-ui][6])

---

# 6. Repository structure

Use a monorepo so frontend, backend, contracts, and event fixtures evolve together.

```text
fleet-agent/
├── apps/
│   ├── web/
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── app-router.tsx
│   │   │   │   ├── providers.tsx
│   │   │   │   └── routes/
│   │   │   ├── components/
│   │   │   │   ├── assistant-ui/
│   │   │   │   ├── projects/
│   │   │   │   ├── process-panel/
│   │   │   │   ├── thread/
│   │   │   │   └── ui/
│   │   │   ├── features/
│   │   │   │   ├── agent-runtime/
│   │   │   │   ├── artifacts/
│   │   │   │   ├── projects/
│   │   │   │   ├── sources/
│   │   │   │   └── threads/
│   │   │   ├── hooks/
│   │   │   ├── lib/
│   │   │   │   ├── api-client.ts
│   │   │   │   ├── assistant-runtime.tsx
│   │   │   │   └── query-client.ts
│   │   │   ├── state/
│   │   │   │   └── workspace-store.ts
│   │   │   └── contracts/
│   │   │       └── generated.ts
│   │   └── tests/
│   │
│   └── api/
│       ├── app/
│       │   ├── api/
│       │   │   ├── agent.py
│       │   │   ├── artifacts.py
│       │   │   ├── projects.py
│       │   │   └── threads.py
│       │   ├── agent/
│       │   │   ├── engine.py
│       │   │   ├── factory.py
│       │   │   ├── signature.py
│       │   │   └── tools/
│       │   ├── agui/
│       │   │   ├── event_bus.py
│       │   │   ├── event_mapper.py
│       │   │   ├── run_coordinator.py
│       │   │   └── trace_reducer.py
│       │   ├── contracts/
│       │   │   ├── agent_state.py
│       │   │   └── domain.py
│       │   ├── persistence/
│       │   │   ├── models.py
│       │   │   ├── repositories.py
│       │   │   └── migrations/
│       │   ├── services/
│       │   ├── settings.py
│       │   └── main.py
│       └── tests/
│
├── packages/
│   └── contracts/
│       ├── agent-workspace-state.schema.json
│       └── fixtures/
│           ├── successful-run.ndjson
│           ├── tool-error-run.ndjson
│           └── forced-submit-run.ndjson
│
├── compose.yaml
├── pnpm-workspace.yaml
└── README.md
```

---

# 7. Phased implementation

## Phase 0 — Architecture and protocol contract

### Work

* Create an architecture decision record for:

  * assistant-ui
  * AG-UI
  * FastAPI
  * DSPy
  * SSE
  * public process trace
* Define the privacy boundary:

  * Raw `next_thought` is never sent to the browser.
  * Raw provider prompts are never returned by the API.
  * Tool inputs and outputs are redacted and size-limited.
* Create `AgentWorkspaceState` schema version 1.
* Create canonical event ordering.
* Create three mocked AG-UI fixture streams:

  * Successful run
  * Tool failure followed by recovery
  * Agent terminates without a valid output
* Pin exact dependency versions in lockfiles.

### Acceptance criteria

* The TypeScript and Python state models validate against the same schema.
* Mock streams can be replayed deterministically.
* No fixture contains raw chain-of-thought.
* A documented migration policy exists for state schema changes.

---

## Phase 1 — Bootstrap the frontend and backend

### Frontend setup

```bash
pnpm create vite apps/web --template react-ts
pnpm add @assistant-ui/react @assistant-ui/react-ag-ui @ag-ui/client
pnpm add @tanstack/react-query react-router-dom zod zustand
pnpm dlx shadcn@latest init -d --base base-ui
```

Configure the assistant-ui style-aware registry:

```json
{
  "registries": {
    "@assistant-ui": "https://r.assistant-ui.com/styles/{style}/{name}.json"
  }
}
```

Then add the initial components:

```bash
pnpm dlx shadcn@latest add \
  resizable \
  sheet \
  tabs \
  scroll-area \
  collapsible \
  badge \
  button \
  separator \
  tooltip \
  skeleton \
  textarea \
  dropdown-menu
```

Add the assistant-ui thread:

```bash
pnpm dlx shadcn@latest add @assistant-ui/thread
```

The style-aware assistant-ui registry resolves Base UI-specific versions when the shadcn style begins with `base-`. ([assistant-ui][2])

### Backend setup

```bash
uv add fastapi uvicorn dspy ag-ui-protocol orjson pydantic-settings
uv add sqlalchemy alembic asyncpg
uv add --dev pytest pytest-asyncio httpx ruff mypy
```

### Infrastructure

* Configure environment validation.
* Configure CORS only for the expected frontend origins.
* Add `/health` and `/ready`.
* Add linting, type-checking, frontend tests, and backend tests to CI.
* Do not add PostgreSQL-dependent application logic yet.

### Acceptance criteria

* Both applications start locally.
* CI runs successfully.
* The frontend displays an empty three-pane route.
* The backend exposes valid health endpoints.

---

## Phase 2 — Implement the AG-UI mock vertical slice

Do this before integrating DSPy.

### Backend endpoint

Create:

```text
POST /api/agent
Content-Type: application/json
Response: text/event-stream
```

The endpoint accepts AG-UI `RunAgentInput` and responds through `EventEncoder`.

The mock stream should emit:

```text
RUN_STARTED
STATE_SNAPSHOT
STATE_DELTA  → understanding running
STATE_DELTA  → understanding completed
STATE_DELTA  → analysis running
TEXT_MESSAGE_START
TEXT_MESSAGE_CONTENT
TEXT_MESSAGE_END
STATE_DELTA  → run completed
RUN_FINISHED
```

### Backend components

Implement:

```python
class RunCoordinator:
    async def stream(self, input_data, request):
        ...
```

```python
class TraceReducer:
    def initial_state(self, thread_id, run_id):
        ...

    def apply(self, command):
        ...

    def create_patch(self, before, after):
        ...
```

```python
class RunEventBus:
    async def publish(self, event):
        ...

    async def subscribe(self):
        ...
```

### SSE requirements

* Pass the request `Accept` header to `EventEncoder`.
* Set `Cache-Control: no-cache`.
* Disable reverse-proxy buffering.
* Emit a terminal event exactly once.
* Detect client disconnects.
* Never return Python exception strings directly to the browser.

### Acceptance criteria

* The AG-UI client can consume the stream.
* Events arrive in deterministic order.
* The initial snapshot always precedes deltas.
* Invalid request bodies return a normal HTTP validation response.
* A simulated error emits `RUN_ERROR`.

---

## Phase 3 — Implement the three-pane workspace shell

### Layout

Use shadcn’s `ResizablePanelGroup`:

```text
Project sidebar:  220–320 px
Conversation:     minimum 560 px
Process panel:    320–560 px
```

Suggested defaults:

```text
Project sidebar: 248 px
Process panel:   400 px
```

The shadcn Resizable component supports horizontal accessible panel groups and keyboard-accessible resizing. ([Shadcn UI][7])

### Desktop behavior

* Left sidebar is collapsible.
* Right panel is collapsible and resizable.
* Panel width is persisted in local storage.
* Conversation remains centered with a sensible maximum content width.
* Composer stays anchored at the bottom.

### Responsive behavior

At narrower widths:

```text
Below 1200 px:
  Process panel becomes a Sheet.

Below 768 px:
  Project sidebar becomes a Sheet.
  Process panel becomes a full-height Sheet.
```

### Components

```text
AgentWorkspace
├── ProjectSidebar
│   ├── WorkspaceHeader
│   ├── NewThreadButton
│   ├── ProjectTree
│   └── UserMenu
├── ConversationPane
│   ├── ConversationHeader
│   ├── Thread
│   └── ActiveRunIndicator
└── ProcessPanel
    ├── ProcessPanelHeader
    ├── ProcessTabs
    └── ProcessPanelContent
```

### Acceptance criteria

* The layout matches the visual direction of the reference.
* Both side panels are independently collapsible.
* Resizing is keyboard accessible.
* Mobile sheets return focus to their triggers.
* Panel preferences survive reload.

---

## Phase 4 — Wire assistant-ui to AG-UI

Create a provider around the workspace:

```tsx
const runtime = useAgUiRuntime({
  agent,
  showThinking: false,
  onError(error) {
    reportClientError(error);
  },
  onCancel() {
    reportRunCancellation();
  },
});
```

Set `showThinking: false` explicitly. The current assistant-ui runtime defaults it to `true` and otherwise renders AG-UI thinking and reasoning events. ([assistant-ui][6])

### Main chat rendering rules

Render in the center:

* User messages
* Final assistant text
* Inline errors
* Compact progress indicator
* Inline artifacts only when they are directly relevant
* Approval UI later

Do not render in the center:

* Raw reasoning messages
* Full tool arguments
* Full tool output
* Every process step
* Debug metadata

Customize the assistant message parts pipeline so detailed tool calls are suppressed or reduced to:

```text
Used 3 tools · View process
```

The detailed content lives in the right panel.

### Acceptance criteria

* Sending a message starts the AG-UI request.
* `RUN_STARTED` changes the thread to running.
* Text events render as an assistant message.
* The cancel action aborts the active HTTP stream.
* No reasoning block appears in the main conversation.

---

## Phase 5 — Implement the process panel

### State consumption

```tsx
const agentState = useAgUiState<AgentWorkspaceState>();
const isRunning = useAuiState((state) => state.thread.isRunning);
```

Do not duplicate agent state in Zustand.

Use Zustand only for:

```text
panel open/closed
selected panel tab
panel width
selected project/thread
```

assistant-ui explicitly distinguishes application state, assistant-ui client state, and AG-UI agent state; follow that separation. ([assistant-ui][4])

### Panel tabs

#### Activity

* Run status and duration
* Current step
* Completed process steps
* Decisions
* Tool calls
* Termination details

#### Sources

* Source title
* Source type
* Excerpt
* Originating tool
* Open-source action
* Copy citation action

#### Artifacts

* File name
* Type
* Size
* Generation status
* Download/open action
* Failure state

### Activity components

```text
RunSummary
ProcessTimeline
ProcessStepCard
DecisionCard
ToolExecutionCard
RunMetrics
TerminationNotice
```

### Process step behavior

Collapsed:

```text
✓ Compare implementation approaches                1.2s
  AG-UI provides the cleanest transport boundary.
```

Expanded:

```text
Summary
AG-UI separates frontend state from the DSPy runtime.

Alternatives
• Direct DSPy stream
• Custom SSE protocol
• AG-UI

Selected
AG-UI

Evidence
2 sources

Tools
1 documentation lookup
```

### Live behavior

* Scroll to the active step only when the user is already near the bottom.
* Do not steal scroll position while the user is inspecting an older step.
* Animate running states with reduced-motion support.
* Highlight new sources and artifacts briefly.
* Automatically open the process panel for the first tool call, but only once per user.

### Acceptance criteria

* State updates appear without parsing messages.
* A full state snapshot renders correctly.
* Every supported JSON Patch operation is tested.
* Empty, running, completed, failed, and cancelled states are designed.
* Long tool results do not break the layout.

---

## Phase 6 — Integrate DSPy ReActV2

## 6.1 Isolate DSPy behind an engine interface

```python
class AgentEngine(Protocol):
    async def run(
        self,
        *,
        user_request: str,
        history: object | None,
        context: "AgentRunContext",
    ) -> "AgentRunResult":
        ...
```

Implementation:

```text
AgentEngine
└── DspyReActV2Engine
```

Do not let FastAPI routes import or inspect ReActV2 internals directly.

This isolation is important because `ReActV2` is currently experimental, is planned to become the canonical `dspy.ReAct` implementation, and the temporary `ReActV2` alias is scheduled for later removal. Pin DSPy while using it. ([DSPy][8])

## 6.2 Strengthen the DSPy Signature

Use explicit user-facing outputs:

```python
class AgentSignature(dspy.Signature):
    """
    Resolve the user's request using available tools when necessary.

    Produce a direct final answer and a concise, user-safe account
    of the approach and decisions. Do not expose hidden reasoning.
    """

    user_request: str = dspy.InputField()

    answer: str = dspy.OutputField(
        desc="Direct final answer to the user."
    )

    process_summary: str = dspy.OutputField(
        desc="Concise user-facing summary of the approach taken."
    )

    key_decisions: list[str] = dspy.OutputField(
        desc="Important decisions made during the process."
    )

    caveats: list[str] = dspy.OutputField(
        desc="Remaining uncertainty, limitations, or risks."
    )
```

These fields produce intentional public explanations. They are not derived by exposing `next_thought`.

## 6.3 Construct the agent

```python
agent = dspy.ReActV2(
    AgentSignature,
    tools=tools,
    max_iters=6,
)
```

Use:

* A bounded `max_iters`
* Native function calling where supported
* Typed tools
* Precise docstrings
* Bounded tool responses
* `track_usage=True`
* Exact dependency pinning

ReActV2 stores structured `dspy.History`, can accept continuation history, returns `termination_reason`, and uses its internal `submit` tool to return typed outputs. ([DSPy][8])

## 6.4 Tool execution model

For the first implementation:

* Keep tools synchronous.
* Execute the DSPy program through an async service boundary.
* Avoid direct async tool functions inside the current ReActV2 loop.
* Put timeouts inside every network-facing tool.
* Return controlled domain objects or bounded strings.

The current ReActV2 implementation executes its tool calls through the synchronous `forward` loop and `_execute_tool_calls`. ([DSPy][9])

## 6.5 Validate termination

Handle at least:

```text
submit
forced_submit
max_iters
empty_tool_calls
parse_error
context_window_exceeded
```

Rules:

* `submit`: normal success.
* `forced_submit`: success with a diagnostic marker.
* Missing `answer`: fail the application run.
* Context exhaustion: display a specific recoverable error.
* Never assume declared outputs exist on every termination path.

ReActV2 may return history and a termination reason without all declared outputs when forced submission fails. ([DSPy][8])

### Acceptance criteria

* A tool-free request succeeds.
* A one-tool request succeeds.
* A multi-tool request succeeds.
* Tool exceptions can be recovered from.
* Missing final output becomes a controlled `RUN_ERROR`.
* Continuation history works across two turns.
* The browser never receives `prediction.history.next_thought`.

---

## Phase 7 — Implement the live DSPy-to-AG-UI event bridge

This is the most important backend component.

### Execution model

```text
FastAPI SSE generator
       │
       ├── emits RUN_STARTED
       ├── emits STATE_SNAPSHOT
       │
       ├── starts DSPy task
       │       │
       │       ├── instrumented tools
       │       ├── result
       │       └── exception
       │
       ├── drains RunEventBus
       ├── converts events to AG-UI
       ├── emits final text
       └── emits terminal run event
```

### Run event bus

Because DSPy may execute in a worker thread, tool instrumentation must publish to the async SSE loop safely.

Recommended shape:

```python
class RunEventBus:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._queue: asyncio.Queue[DomainEvent] = asyncio.Queue()

    def publish_from_worker(self, event: DomainEvent) -> None:
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            event,
        )

    async def next(self) -> DomainEvent:
        return await self._queue.get()
```

### Tool wrapper

```text
instrumented tool called
        │
        ├── publish ToolStarted
        ├── invoke actual tool
        ├── publish SourceDiscovered or ArtifactCreated
        ├── publish ToolCompleted
        └── return result to ReActV2
```

Each wrapper must:

* Generate a stable tool-call ID.
* Record start time.
* Sanitize arguments.
* Emit `TOOL_CALL_START`.
* Emit `TOOL_CALL_ARGS`.
* Emit `TOOL_CALL_END`.
* Execute the function.
* Emit `TOOL_CALL_RESULT`.
* Update `AgentWorkspaceState`.
* Preserve the real return value for DSPy.
* Replace unsafe exceptions with controlled tool errors.

### Trace reducer

Domain event:

```python
ToolStarted(
    tool_call_id="tool_123",
    name="search_docs",
    input_preview='query="DSPy ReActV2"',
)
```

becomes a JSON Patch:

```json
[
  {
    "op": "add",
    "path": "/toolCalls/-",
    "value": {
      "id": "tool_123",
      "name": "search_docs",
      "status": "running",
      "inputPreview": "query=\"DSPy ReActV2\""
    }
  }
]
```

### Safe process steps

For the MVP, produce live steps deterministically:

```text
Understanding request
Selecting relevant tools
Searching documentation
Reviewing tool results
Preparing response
```

At completion, enrich them with:

```text
process_summary
key_decisions
caveats
```

Do not ask the model to publish raw intermediate thought.

A later version can add a dedicated `report_progress` tool with a constrained public-summary schema, but it should not be required for the initial implementation.

### Acceptance criteria

* Tool activity appears before the final response.
* Concurrent runs never leak events across threads.
* Every tool event carries the correct `runId` and `toolCallId`.
* Tool outputs are truncated and redacted.
* The stream remains valid after a recoverable tool error.
* A run always ends with one terminal state.

---

## Phase 8 — Map the final DSPy result into the UI

ReActV2 produces its typed final outputs through `submit`, so the complete final answer may only be available when the agent loop ends. ([DSPy][8])

For the first version:

1. Stream process and tool activity live.
2. Display a temporary main-chat status:

   * “Understanding the request…”
   * “Researching…”
   * “Comparing alternatives…”
3. When DSPy returns:

   * Emit `TEXT_MESSAGE_START`.
   * Emit one or more `TEXT_MESSAGE_CONTENT` events.
   * Emit `TEXT_MESSAGE_END`.
4. Update process state with decisions and caveats.
5. Emit `RUN_FINISHED`.

Do not fake token-level streaming by arbitrarily splitting a completed answer.

### Optional later enhancement

Add a presentation stage:

```text
ReActV2 structured result
        │
        ▼
AnswerPresenter
        │
        ▼
streamed final response
```

This adds another LM call and should only be introduced after measuring whether token streaming materially improves the experience.

---

## Phase 9 — Projects, threads, and persistence

### Database model

| Table            | Purpose                                         |
| ---------------- | ----------------------------------------------- |
| `projects`       | Workspace/project metadata                      |
| `threads`        | Conversation sessions within a project          |
| `messages`       | Persisted AG-UI messages                        |
| `runs`           | One agent execution per user turn               |
| `run_events`     | Ordered domain or AG-UI event log               |
| `run_states`     | Latest process-panel snapshot                   |
| `dspy_histories` | Versioned server-side DSPy continuation history |
| `sources`        | Retrieved evidence                              |
| `artifacts`      | Generated files and storage metadata            |

### Recommended fields

```text
projects
  id
  owner_id
  name
  created_at
  updated_at

threads
  id
  project_id
  title
  status
  last_run_id
  created_at
  updated_at

runs
  id
  thread_id
  status
  termination_reason
  started_at
  finished_at
  token_usage
  error_code

dspy_histories
  thread_id
  schema_version
  dspy_version
  history_json
  updated_at
```

### DSPy history

Store `dspy.History`:

* Server-side only
* Encrypted at rest when appropriate
* With its DSPy package version
* With an application serialization version
* Separately from the public process trace

Before the next turn:

```text
load DSPy history
        ↓
pass history=...
        ↓
execute ReActV2
        ↓
persist returned history
```

ReActV2 explicitly supports passing returned structured history back through its `history` input. ([DSPy][8])

### REST endpoints

```text
GET    /api/projects
POST   /api/projects

GET    /api/projects/{project_id}/threads
POST   /api/projects/{project_id}/threads

GET    /api/threads/{thread_id}/bootstrap
PATCH  /api/threads/{thread_id}
DELETE /api/threads/{thread_id}

GET    /api/threads/{thread_id}/sources
GET    /api/threads/{thread_id}/artifacts

GET    /api/artifacts/{artifact_id}
```

`/bootstrap` should return:

```json
{
  "thread": {},
  "messages": [],
  "agentState": {},
  "latestRun": {}
}
```

### Thread switching

Use a custom project/thread sidebar visually, but connect it to a thin assistant-ui thread adapter.

Current assistant-ui AG-UI multi-thread support is marked experimental, so isolate it in one module:

```text
features/threads/assistant-thread-adapter.ts
```

Do not let the rest of the application depend directly on its unstable shape. ([assistant-ui][6])

### Acceptance criteria

* Reload restores messages and the latest process state.
* Switching threads restores the correct thread and no other.
* DSPy continuation history is not sent to the client.
* Deleting a thread also handles associated artifacts according to retention policy.
* Concurrent requests cannot update the wrong thread.

---

## Phase 10 — Sources and artifacts

### Sources

Define a standard source result contract for retrieval tools:

```python
class SourceResult(BaseModel):
    id: str
    title: str
    source_type: str
    uri: str | None
    excerpt: str | None
    metadata: dict[str, object]
```

Tool wrappers should publish `SourceDiscovered` events.

The process panel should:

* Deduplicate by canonical URI or document identifier.
* Show the originating tool call.
* Display a safe excerpt.
* Allow opening or copying the reference.
* Avoid rendering untrusted HTML.

### Artifacts

Define:

```python
class ArtifactResult(BaseModel):
    id: str
    name: str
    media_type: str
    storage_key: str
    size_bytes: int | None
```

Artifact lifecycle:

```text
ArtifactStarted
       ↓
state: generating
       ↓
upload to object storage
       ↓
ArtifactReady
       ↓
state: ready
```

The browser should receive a controlled artifact ID or short-lived signed URL, never a server filesystem path.

### Inline artifact behavior

* All artifacts appear in the right panel.
* Important deliverables can additionally appear inline through a `CUSTOM` event.
* Clicking an inline artifact opens the Artifacts tab and selects it.

### Acceptance criteria

* Artifact generation has loading, success, and failure states.
* Access is authorized by project and user.
* File names cannot create path traversal.
* Expired download URLs are refreshed safely.
* Deleted threads follow a defined artifact retention policy.

---

## Phase 11 — Cancellation, errors, and recovery

### Cancellation semantics

Define cancellation accurately:

* Frontend cancel stops the active AG-UI stream.
* FastAPI detects disconnection.
* `RunCoordinator` marks the run cancelled.
* Tool wrappers check a cancellation token before expensive work.
* Provider calls already in progress may not stop immediately.
* No new tool starts after cancellation is observed.
* Late events are discarded.

### Error categories

Use stable public codes:

```text
agent_timeout
agent_no_output
agent_parse_error
agent_context_limit
tool_timeout
tool_failed
tool_unauthorized
rate_limited
run_cancelled
internal_error
```

The client sees:

```json
{
  "code": "tool_timeout",
  "message": "The documentation lookup timed out."
}
```

It does not see:

```text
stack traces
provider request bodies
API keys
database errors
raw tool exceptions
```

### Recovery behavior

* Tool failure: allow ReActV2 to recover where possible.
* Context limit: preserve the thread but mark the run incomplete.
* Network interruption: restore the latest persisted state after reload.
* Duplicate run request: enforce idempotency by `runId`.
* Server restart: mark orphaned running runs as interrupted.

### Acceptance criteria

* Cancel produces a stable UI state.
* A tool timeout does not leave the panel permanently running.
* A lost browser connection does not corrupt the thread.
* Every failed run has a public code and internal correlation ID.

---

## Phase 12 — Security and privacy hardening

Implement before production:

* Server-side authentication
* Project/thread authorization on every route
* Exact CORS origins
* Per-user run concurrency limits
* Request size limits
* Tool argument validation
* Tool output size limits
* Artifact type and size restrictions
* Signed artifact access
* Markdown sanitization
* Source URL validation
* Prompt-injection-aware tool boundaries
* Secrets only in backend environment configuration
* Log redaction
* Data retention policy

### Chain-of-thought boundary

Enforce this with code, not only instructions:

```text
dspy.History
    │
    ├── stored server-side for continuation
    │
    └── passed through PublicTraceMapper
            │
            ├── tool names
            ├── safe summaries
            ├── sources
            ├── decisions
            └── artifacts
```

The mapper must explicitly ignore:

```text
next_thought
raw prompts
system instructions
provider metadata
unredacted tool payloads
```

Add an automated test that scans every AG-UI fixture and integration stream for prohibited fields.

---

# 8. Testing plan

## Contract tests

Test:

* Every AG-UI event serializes.
* Event ordering is valid.
* State deltas apply to the expected state.
* Python and TypeScript schemas remain compatible.
* Unsupported state versions fail clearly.
* Tool IDs correctly match results.
* Every run has exactly one terminal state.

## Backend unit tests

Cover:

```text
TraceReducer
RunEventBus
RunCoordinator
Tool instrumentation
PublicTraceMapper
DSPy termination mapping
History serialization
Source deduplication
Artifact authorization
```

Use an `AgentEngine` test double for most tests. Do not call a real provider in normal CI.

## Backend integration tests

Scenarios:

1. No-tool answer
2. One successful tool
3. Multiple tools
4. Tool failure and recovery
5. Tool timeout
6. Forced submit
7. Missing output
8. Client disconnect
9. Two concurrent runs
10. Two threads with independent histories

## Frontend component tests

Test:

* Process state rendering
* Step expansion
* Source selection
* Artifact status
* Empty state
* Failed state
* Long content
* Responsive Sheet behavior
* Keyboard resizing
* Reduced motion

## End-to-end tests

Use Playwright with a deterministic mocked AG-UI server:

```text
create project
create thread
send request
observe live process step
observe tool completion
receive final answer
open source
open artifact
reload
verify restoration
switch thread
verify isolation
cancel run
```

## Load tests

Measure:

* Concurrent SSE connections
* Time to `RUN_STARTED`
* Time to first state update
* Time to first tool event
* Time to final answer
* Database write pressure
* Redis/pub-sub pressure when introduced
* Provider concurrency and rate-limit behavior

---

# 9. Observability

Attach these identifiers to every log and metric:

```text
request_id
project_id
thread_id
run_id
message_id
tool_call_id
user_id
```

### Metrics

```text
agent_runs_total
agent_run_duration_ms
agent_run_first_event_ms
agent_run_termination_reason
agent_run_errors_total
agent_tool_calls_total
agent_tool_duration_ms
agent_tool_errors_total
agent_input_tokens
agent_output_tokens
active_sse_connections
```

### Logging policy

Log:

* Event type
* IDs
* Durations
* Status
* Error code
* Payload size

Do not log by default:

* Full prompts
* Full responses
* Raw `dspy.History`
* Raw tool results
* Access tokens
* Artifact contents

---

# 10. Deployment plan

## Development

```text
Vite dev server
FastAPI/Uvicorn
PostgreSQL container
Local object storage or MinIO
Single backend process
```

## Staging

```text
Static frontend deployment
FastAPI container
Managed PostgreSQL
Object storage
One or more API workers
Redis when multiple workers are enabled
```

## Production considerations

* Place frontend and API behind the same origin where possible.
* Disable proxy buffering for SSE.
* Use long enough ingress timeouts for agent runs.
* Use Redis or another shared run/event backend before horizontally scaling.
* Do not depend on in-memory thread or run state across workers.
* Gracefully drain open SSE requests during deployment.
* Mark interrupted runs during startup reconciliation.

---

# 11. Recommended PR sequence

## PR 1 — Workspace scaffolding

* Frontend and backend projects
* CI
* Shared contract directory
* Health endpoints

## PR 2 — Three-pane shell

* Project sidebar
* Conversation area
* Process panel
* Responsive behavior
* Resizable layout

## PR 3 — AG-UI mock transport

* FastAPI SSE endpoint
* EventEncoder
* Mock run
* assistant-ui runtime
* Final message rendering

## PR 4 — Agent state panel

* `AgentWorkspaceState`
* `STATE_SNAPSHOT`
* `STATE_DELTA`
* Activity, Sources, and Artifacts tabs

## PR 5 — DSPy engine

* Signature
* ReActV2 factory
* One typed tool
* Result and termination mapping
* Version pinning

## PR 6 — Tool instrumentation

* Run event bus
* Instrumented tool wrappers
* Tool events
* Live process updates
* Redaction

## PR 7 — Persistence and threads

* Projects and threads
* Messages
* Run records
* DSPy history
* Thread restoration and switching

## PR 8 — Sources and artifacts

* Source model
* Artifact storage
* Panel integration
* Access control

## PR 9 — Hardening

* Cancellation
* Error taxonomy
* Security controls
* Observability
* Load tests
* Deployment configuration

Each PR should remain independently testable. Do not combine the transport, DSPy integration, persistence, and UI shell into one initial change.

---

# 12. MVP definition of done

The first production-capable version is complete when:

* A user can create a project and thread.
* A message is sent through assistant-ui and AG-UI.
* FastAPI invokes the DSPy ReActV2 engine.
* Tool activity appears live in the process panel.
* The main chat remains concise.
* The final answer appears after successful submission.
* The process panel shows public summaries, decisions, sources, and artifacts.
* Raw DSPy thoughts are never sent to the browser.
* Reload restores the conversation and process state.
* Thread switching is isolated and reliable.
* Tool failures and agent termination have designed UI states.
* Runs are observable by correlation ID.
* Auth, authorization, redaction, and rate limits are enabled.
* Dependency versions are pinned.
* Contract, integration, accessibility, and end-to-end tests pass.

The first vertical slice should stop after **PR 4**: a mocked AG-UI run must successfully drive both the assistant-ui conversation and the state-based right panel before DSPy is introduced.

[1]: https://www.assistant-ui.com/docs/runtimes/ag-ui "AG-UI Agent Runtime — assistant-ui"
[2]: https://www.assistant-ui.com/docs/base-ui "Radix UI and Base UI — assistant-ui"
[3]: https://docs.ag-ui.com/sdk/python/encoder/overview "Overview - Agent User Interaction Protocol"
[4]: https://www.assistant-ui.com/docs/runtimes/ag-ui/agent-state "Agent state — assistant-ui"
[5]: https://docs.ag-ui.com/sdk/python/core/events "Events - Agent User Interaction Protocol"
[6]: https://www.assistant-ui.com/docs/runtimes/ag-ui/runtime-options "Runtime options — assistant-ui"
[7]: https://ui.shadcn.com/docs/components/base/resizable "Resizable - shadcn/ui"
[8]: https://dspy.ai/diving-deeper/react/ "ReAct and ReActV2 - DSPy"
[9]: https://dspy.ai/api/modules/ReActV2/ "ReActV2 - DSPy"
