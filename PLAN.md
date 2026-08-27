# Fleet Agent: UI-First DSPy Workbench Plan

A comprehensive architectural and engineering roadmap to elevate **Fleet Agent** into a modern, UI-first workbench for **DSPy 3.3+**. This plan covers the persistent app shell, modern reference sidebar, real-time dual-field streaming, code-level program evolution (`dspy.Flex` + `dspy.GEPA`), tools catalog, MCP connectors, and interactive evaluation.

---

## Architecture & Vision

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           PERSISTENT APP SHELL                                         │
├────────────────────┬───────────────────────────────────────────────────────────────────────────────────┤
│                    │ Top Nav Bar: Project [Market Analysis]                                            │
│                    │ ┌───────────────────┬───────────────────┬───────────────────┬───────────────────┐ │
│  PROJECT SIDEBAR   │ │ 💬 Workspace     │ ⚡ Optimizer       │ 🛠️ Tools          │ 🔌 Connectors     │ │
│  (Always Mounted)  │ └───────────────────┴───────────────────┴───────────────────┴───────────────────┘ │
│                    ├───────────────────────────────────────────────────────────────────────────────────┤
│  • New chat (+)    │                                                                                   │
│  • Optimizer (⚡)   │                                                                                   │
│  • Tools (🛠️)      │                                                                                   │
│  • Connectors (🔌) │                                                                                   │
│  • Scheduled / Sec │                               ACTIVE ROUTE OUTLET                                 │
│  • Projects (Tree) │                   (Workspace / Optimizer / Tools / Connectors)                    │
│  • Footer Bar      │                                                                                   │
│    (Qredence/Voice)│                                                                                   │
└────────────────────┴───────────────────────────────────────────────────────────────────────────────────┘
```

---

## Milestone 1: Persistent Root App Shell & Reference Sidebar

**Goal:** Hoist navigation into a persistent root layout that preserves sidebar scroll/collapse state across all routes, implementing the exact dark-theme styling, iconography, and layout from the reference design.

### 1.1 Persistent App Shell & Layout
- [x] Create `AppShell` and `ProjectNavTabs` (`apps/web/src/components/layout/project-nav-tabs.tsx`):
  - Tabs: **Workspace** (`/projects/:id`), **Optimizer** (`/projects/:id/optimizer`), **Tools** (`/projects/:id/tools`), **Connectors** (`/projects/:id/connectors`).
  - Active state styling with pill highlights and seamless route transitions.
- [x] Refactor `apps/web/src/app/app-router.tsx` to include routes for Workspace, Optimizer, Tools, and Connectors.

### 1.2 High-Fidelity Shadcn Base-UI Sidebar
- [x] Refactor `apps/web/src/components/projects/project-sidebar.tsx`:
  - **Header**: Workspace selector dropdown (`Fleet Agent ⌵`) + Quick Search icon (`⌘K`) + Notifications bell icon.
  - **Top Action & Navigation List**:
    - `New chat` with compose icon (`SquarePen`) and right shortcut badge (`+`).
    - `Optimizer` (`Sparkles`) linking to `/projects/:projectId/optimizer`.
    - `Tools` (`Wrench`) linking to `/projects/:projectId/tools`.
    - `Connectors` (`Plug`) linking to `/projects/:projectId/connectors`.
    - `Scheduled` (`Clock`) and `Security` (`Shield`).
  - **Projects Section**:
    - Project badges with custom accent colors:
      - `fleet-agent`: `FlaskConical` (`text-pink-400`).
      - `fleet-prime-agent`: `Hexagon` (`text-amber-400`).
      - `fleet-rlm`: `Boxes` (`text-emerald-400`).
      - Default: `Folder` / `FolderOpen`.
    - Selected project pill state (`rounded-lg bg-accent/80 font-medium`).
    - Thread sub-items with hierarchy indentation, right-aligned git branch/PR indicators (`GitPullRequest` in `text-purple-400`), and empty state (`No chats`).
    - Collapsible "Show more" expander for projects and thread lists.
  - **Recents Section**: Quick jump list section header.
  - **Footer Bar**: Organization identity (`Qredence`) + Voice toggle (`Voice` with `AudioLines` wave) + Help link (`CircleHelp`).

---

## Milestone 2: Real-Time Dual-Field Streaming (`dspy.streamify`)

**Goal:** Eliminate artificial post-run delay by using native DSPy streaming to render conversation text and process step summaries simultaneously in real time.

### 2.1 Backend Engine & Coordinator Updates
- [ ] Update `LiveDSPyCoordinator` (`apps/api/app/agui/live_coordinator.py`):
  - Replace static execution + `_chunk_text()` with `dspy.streamify`.
  - Configure two `dspy.streaming.StreamListener` instances:
    1. `StreamListener(signature_field_name="answer")`
    2. `StreamListener(signature_field_name="process_summary")`
  - Stream `answer` tokens via `TextMessageContentEvent` to assistant-ui.
  - Stream `process_summary` tokens via `StateDeltaEvent` into `state.steps[activeStep].publicSummary`.

### 2.2 Frontend Synchronized Multi-Pane Streaming
- [ ] Update `ProcessStepCard` (`apps/web/src/components/process-panel/process-step-card.tsx`):
  - Add live token accumulation and pulsing cursor for the active step.
- [ ] Update `RunMetrics` (`apps/web/src/components/process-panel/run-metrics.tsx`):
  - Display live millisecond duration counter ticking during generation.

---

## Milestone 3: Optimizer Studio (`dspy.Flex` + `dspy.GEPA` + Evaluation)

**Goal:** Provide an interactive studio to optimize prompts, few-shot demonstrations, and full Python module code using DSPy's evolutionary program architecture.

### 3.1 Backend: Flex Module & Optimization Engine
- [ ] Integrate `dspy.Flex` into `apps/api/app/agent/`:
  - Wrap agent signatures in `dspy.Flex(AgentSignature, tools=...)` with sandboxed execution via `dspy.PythonInterpreter` (Deno/Pyodide).
- [ ] Implement Optimization Endpoints in `apps/api/app/api/optimizer.py`:
  - `POST /api/projects/{project_id}/optimizer/run`: Launches background `dspy.GEPA` / `dspy.MIPROv2` optimization.
  - `GET /api/projects/{project_id}/optimizer/candidates`: Returns compiled program generations with Pareto scores and `module_src`.
  - `POST /api/projects/{project_id}/optimizer/promote`: Promotes a candidate generation to active project runtime.
- [ ] Compound Evaluation Metrics:
  - Implement `dspy.evaluate.CompleteAndGrounded` and `dspy.evaluate.SemanticF1` with structured feedback for GEPA reflection.

### 3.2 Frontend: Optimizer Studio (`apps/web/src/features/optimizer/`)
- [ ] Build `OptimizerRoute` (`apps/web/src/app/routes/optimizer-route.tsx`):
  - **Left (Candidate Generations)**: List of compiled iterations (`Gen 1 Baseline`, `Gen 2 MIPROv2`, `Gen 3 GEPA Evolved`) with score badges.
  - **Center (Code & Architecture Inspector)**:
    - Syntax-highlighted Python viewer for optimizer-authored `module_src`.
    - Side-by-side diff viewer highlighting additions and deletions across generations.
  - **Right (Pareto & Feedback Analysis)**:
    - Metric score gauges (Completeness, Groundedness, Semantic F1).
    - Interactive Pareto frontier scatter plot (Accuracy Score vs. Latency / Token Cost).
    - Natural language reflection feedback logs explaining optimizer decisions.
- [ ] Chat Turn-to-Example Feedback Action:
  - Add thumbs up/down and edit actions in assistant-ui to save turns directly as versioned `dspy.Example` entries.

---

## Milestone 4: Tools Catalog & Policy Inspector

**Goal:** Provide a dedicated space to inspect registered DSPy tools, parameter schemas, execution constraints, and test executions.

### 4.1 Backend Tool Schema & Simulator Endpoints
- [ ] Add `apps/api/app/api/tools.py`:
  - `GET /api/projects/{project_id}/tools`: Returns metadata for registered tools (`read_only`, `idempotent`, `timeout_seconds`, `max_output_chars`, JSON schema).
  - `POST /api/projects/{project_id}/tools/{tool_name}/execute`: Sandboxed test execution endpoint for debugging.

### 4.2 Frontend Tools Catalog (`apps/web/src/features/tools/`)
- [ ] Build `ToolsRoute` (`apps/web/src/app/routes/tools-route.tsx`):
  - **Left Pane (Tool Catalog)**: Searchable list of registered tools with category badges (`Built-in`, `MCP`, `REPL`, `Custom`).
  - **Right Pane (Tool Inspector)**:
    - Docstring and parameter schema visualizer.
    - Policy tags: `Read-Only`, `Idempotent`, `Parallelizable`, `Requires Approval`.
    - Interactive tool execution simulator with live JSON argument input and output preview.

---

## Milestone 5: Connectors Hub & Model Context Protocol (MCP)

**Goal:** Enable users to connect remote and local MCP servers, databases, and APIs, dynamically turning external endpoints into DSPy tools.

### 5.1 Backend MCP Bridge
- [ ] Integrate `dspy.Tool.from_mcp_tool` in `apps/api/app/agent/tools/mcp.py`:
  - Support streamable HTTP, SSE, and stdio MCP server transports.
  - Dynamically discover and register MCP tools into `ToolRegistry`.
- [ ] Add persistence and CRUD endpoints for MCP server configurations in `apps/api/app/api/connectors.py`.

### 5.2 Frontend Connectors Hub (`apps/web/src/features/connectors/`)
- [ ] Build `ConnectorsRoute` (`apps/web/src/app/routes/connectors-route.tsx`):
  - Active connectors grid with health status, ping latency, and exposed tool counts.
  - **Add Connector Modal**: Configure server URLs, stdio commands, or API keys with live handshake verification (`client.list_tools()`).
  - **Tool Mapping Drawer**: Individually toggle specific tools exposed by an MCP connection.

---

## Milestone 6: Advanced Context Reasoning & Evidence Citations (`dspy.RLM` + `Citations`)

**Goal:** Support large-context data analysis through recursive code acting and connect assistant response claims directly to evidence sources.

### 6.1 Recursive Language Model (`dspy.RLM`)
- [ ] Integrate `dspy.RLM` replacing deprecated `CodeAct`:
  - Place large dataframes or document sets into sandboxed REPL variables.
- [ ] Frontend REPL Terminal:
  - Display streamed Python code execution snippets, stdout, and stderr in `terminal-block.tsx`.
  - Render computed CSV data tables and SVG charts in the **Artifacts Tab**.

### 6.2 Connected Evidence Citations (`dspy.experimental.Citations`)
- [ ] Integrate `dspy.experimental.Citations` in signature output fields.
- [ ] Chat Citation Pills:
  - Render interactive inline `[1]`, `[2]` citation pills in assistant-ui text.
  - Hovering displays quoted excerpt tooltips; clicking auto-scrolls to and highlights the corresponding card in the **Sources Tab**.

---

## Execution Phasing & Dependency Graph

```text
Milestone 1 (Persistent Shell & Reference Sidebar)
   │
   ├──► Milestone 2 (Real-Time Dual-Field Streaming)
   │       │
   │       └──► Milestone 6 (RLM Terminal & Citations)
   │
   ├──► Milestone 4 (Tools Catalog & Inspector)
   │       │
   │       └──► Milestone 5 (Connectors Hub & MCP)
   │
   └──► Milestone 3 (Optimizer Studio: dspy.Flex + GEPA)
```

---

## Verification & Acceptance Criteria

1. **Sidebar Persistence**: Navigating between Workspace, Optimizer, Tools, and Connectors maintains project selection, scroll position, and panel dimensions with zero remounting flicker.
2. **Design Parity**: Sidebar matches the reference image (custom project icon colors, PR branch badges, dark theme tokens, and bottom footer bar).
3. **Streaming Quality**: Conversation answers and process summaries stream simultaneously with zero artificial delay.
4. **Optimization Lifecycle**: Users can trigger a GEPA optimization run, view evolved Python source code diffs in `dspy.Flex`, inspect Pareto score improvements, and promote winning candidates to production.
5. **Contract Safety**: All new state schemas strictly adhere to `packages/contracts/agent-workspace-state.schema.json` without leaking internal model chain-of-thought or provider credentials.
