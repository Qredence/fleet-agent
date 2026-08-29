# Fleet Agent — Architecture

An experimental agent workbench built around **DSPy 3.3.1**. Multi-step agent
work that is useful, inspectable, and recoverable — a direct answer plus a
persistent, browser-visible agent workspace.

Render the diagrams below in any Mermaid-capable viewer (GitHub, GitLab,
Obsidian, mermaid.live). An interactive, themed version is also available in
[`docs/architecture.html`](architecture.html) (open in a browser).

- **Frontend**: React 19 + Vite, assistant-ui 0.15 + AG-UI process panel.
- **Backend**: FastAPI, DSPy ReActV2 / staged strategy, Pinia-free AG-UI SSE.
- **Data**: PostgreSQL 17 (`compose.yaml`), Alembic migrations, local artifacts.

---

## 1 · System Context

```mermaid
flowchart LR
    USER["👤 User\nbrowser operator"] --> UI["React workspace\napps/web"]

    subgraph FRONT["Frontend · React 19"]
        UI --> CHAT["assistant-ui\nconversation + inline run activity"]
        UI --> PP["AG-UI process panel\nSources · Artifacts · Explorer"]
    end

    subgraph API["Backend · FastAPI (apps/api)"]
        ROUTES["REST + SSE routes"] --> COORD["Run coordinator\nAgentEngine boundary"]
        COORD --> PUBLIC["Public-state reducer\nAgentWorkspaceState"]
    end

    CHAT -->|"REST · SSE (SSE /api/agent)"| ROUTES
    PP -->|"REST · SSE"| ROUTES

    subgraph ENG["DSPy engine layer"]
        PUBLIC --> DSPY["dspy.ReActV2 / staged strategy"]
        DSPY --> TOOLS["typed tools"]
    end

    TOOLS -->|"search · report"| DOCS["documentation corpus"]
    TOOLS -->|"optional web"| TAV["Tavily web_search / fetch_page"]
    DSPY -->|"model calls"| LM["OpenAI-compatible model\n(via LiteLLM / dspy.LM)"]

    subgraph DATA["Persistence"]
        PUBLIC --> PG[("PostgreSQL 17")]
        TOOLS --> ART("[artifacts 📄]")
    end
```

---

## 2 · Component Diagram

```mermaid
flowchart TB
    subgraph API["FastAPI app (create_app)"]
        SW["RequestId & SecurityHeaders middleware\nCORS (exact origins only)"]
        R1["/api/agent · POST → SSE"]
        R2["/api/projects · /api/threads"]
        R3["/api/tools · /api/artifacts · /api/metrics"]
    end

    subgraph AGENTSVC["app.agent"]
        E["AgentEngine (Protocol)\nDspyAgentEngine | StagedDspyEngine"]
        SIG["AgentSignature fields:\nanswer · process_summary · key_decisions · caveats"]
        F["factory & EngineBuilder\nruns create run-scoped engines"]
        TC["ToolRegistry + catalog\n(search_docs · write_report · get_current_time · web_*)"]
        CB["AgUiRunCallback\n(DSPy → domain events)"]
    end

    subgraph AGUI["app.agui"]
        BC["RunEventBus"]
        LC["LiveCoordinator\nexactly-once terminal settlement"]
        RC["RunCoordinator\nfixture replay"]
        EMP["EventMapper\ndomain → AG-UI"]
        TR["TraceReducer\nJsonPatch STATE_DELTA"]
    end

    subgraph PERS["app.persistence"]
        MOD["models: projects · threads · messages\nruns · run_states · dspy_histories\nsources · source_occurrences · artifacts"]
        MIG["Alembic migrations"]
        REPO["repositories"]
    end

    subgraph SVC["app.services"]
        ART("artifact_storage")
        RPI("run_persistence")
        RUNI("run_input · source_identity")
        METR("metrics registry")
        HIST("history_safety · mock_run")
    end

    SW --> R1; SW --> R2; SW --> R3
    R1 --> LC; R2 --> LC; R2 --> RC
    LC --> E; RC --> MOD
    E --> F; E --> SIG; F --> TC; E --> CB
    CB --> BC; BC --> EMP; EMP --> TR; EMP --> LC
    LC --> PERS; PERS --> MOD; MOD --> MIG; MOD --> REPO
    ART --> E; RPI --> LC; METR --> LC
```

---

## 3 · Agent Run Flow (engine mode)

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser (assistant-ui)
    participant A as /api/agent (FastAPI)
    participant LC as LiveCoordinator
    participant E as AgentEngine (DSPy)
    participant LM as Model (LiteLLM)
    participant P as PostgreSQL

    U->>A: POST /api/agent (AG-UI RunAgentInput, Accept: SSE)
    A->>LC: gate via run_semaphore (max_concurrent_runs)
    LC->>LC: create RunEventBus + engine (EngineBuilder)
    LC->>E: await run(user_request, history, context)
    E->>LM: DSPy ReActV2 / staged loop (max_iters, JSONAdapter)
    E-->>LC: AgentStreamUpdate / AgentRunResult
    E-->LC: callbacks (ToolStart/End, LmStart, ...)
    LC->>P: persist run, run_state, sources, artifacts
    LC->>A: map domain → AG-UI events (StateDelta, Tool*, Text*)
    A-->>U: SSE stream (STREAM, STATE_DELTA, DONE/RUN_ERROR)
    Note over A,U: history (raw next_thought) stays server-side
```

**Fixtures mode** replays deterministic, provider-free AG-UI streams
(`packages/contracts/fixtures`); **engine mode** uses the live DSPy bridge.

---

## 4 · Public State Contract

Source of truth: `packages/contracts/agent-workspace-state.schema.json` (v1).
Payloads carry `schemaVersion`; generated TS and Python models come from the
schema, never handwritten.

```mermaid
flowchart LR
    SC["AgentWorkspaceState\nschemaVersion · threadId · run\nsteps · decisions · toolCalls\nsources · artifacts · metrics"] --> TS["generated TS type\napps/web/src/contracts/generated.ts"]
    SC --> PYM["generated Python model\napps/api/app/contracts"]

    subgraph SYNC["AG-UI synchronization"]
        SN["STATE_SNAPSHOT\n(one versioned bootstrap)"] --> UI
        DL["STATE_DELTA\n(JsonPatch trace-reduced)"] --> UI
    end
    UI["Browser process panel\nuseAgUiState<AgentWorkspaceState>()"]
```

**Exposed (safe):** run status, active step, tool activity, sources, decisions,
caveats, metrics, sanitized artifacts.
**Never crosses:** raw `next_thought`, `dspy.History`, provider prompts, raw
tool arguments, stack traces, unsanitized responses, credentials.

---

## 5 · Runtime & Persistence

```mermaid
flowchart TB
    subgraph DEV["Local dev (pnpm + uv)"]
        W["dev:web — Vite :5173"]
        A["dev:api — fastapi dev :8000"]
    end
    PG[("PostgreSQL 17\ncompose.yaml · :5432")] --> VOL[("volume: postgres-data")]
    W -->|"REST + SSE\n(exact CORS origins)"| A
    A -->|"asyncpg"| PG

    subgraph TOOLING["Validation"]
        WEBT["web: lint · test · tsc build · contracts:sync"]
        APIT["api: ruff · mypy · pytest\nalembic upgrade head"]
        CI[".circleci"]
    end
    A --> APIT; W --> WEBT; APIT --> CI; WEBT --> CI
```

---

### Key invariants

- **URL owns state** — active project & thread: `/projects/:id/threads/:id`.
- **No mirrored agent state** — process panel reads AG-UI state directly.
- **One versioned bootstrap** — thread restoration fetches one versioned
  snapshot; fallback uses raw `fetchBootstrap`.
- **Scoped DSPy** — `dspy.context(...)` only, never global `dspy.configure`.
- **Alembic migrations** for persistence; engine runs require an existing thread.
- **Contract workflow**: edit schema → `contracts:sync` (TS) → regenerate Python
  model → run freshness tests.
