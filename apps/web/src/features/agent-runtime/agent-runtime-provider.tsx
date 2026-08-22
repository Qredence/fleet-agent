import { HttpAgent } from '@ag-ui/client'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { useAgUiRuntime, useAgUiSetState } from '@assistant-ui/react-ag-ui'
import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { buildHistoryAdapter } from '@/features/threads/assistant-thread-adapter'
import { ArtifactDataUIRegistration } from '@/features/artifacts/artifact-data-ui'
import { fetchBootstrap } from '@/features/threads/threads-api'

const AGENT_URL = `${
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
}/api/agent`

const API_KEY: string | undefined = import.meta.env.VITE_API_KEY || undefined

/**
 * AG-UI runtime for the workspace: one HttpAgent to the FastAPI SSE endpoint.
 *
 * `showThinking: false` is deliberate — the ProcessPanel renders the
 * intentional user-safe trace from agent state; reasoning blocks stay hidden.
 * When `threadId` is set, the history adapter restores persisted AG-UI
 * messages and RestoreAgentState seeds the process panel's last snapshot.
 */
export function AgentRuntimeProvider({
  threadId,
  children,
}: {
  threadId?: string
  children: ReactNode
}) {
  const agent = useMemo(
    () =>
      new HttpAgent({
        url: AGENT_URL,
        ...(API_KEY ? { headers: { 'X-API-Key': API_KEY } } : {}),
      }),
    [],
  )

  // Bind the agent's wire threadId to the URL thread. Without this the client
  // invents a fresh id and engine mode 404s (runs belong to persisted threads).
  useEffect(() => {
    if (threadId) {
      agent.threadId = threadId
    }
  }, [agent, threadId])

  const adapters = useMemo(
    () => (threadId ? { history: buildHistoryAdapter(threadId) } : undefined),
    [threadId],
  )

  const runtime = useAgUiRuntime({
    agent,
    showThinking: false,
    adapters,
    onError: (error) => {
      // Structured client error reporting arrives with observability (PR 9).
      console.error('[ag-ui] run error', error)
    },
    onCancel: () => {
      console.info('[ag-ui] run cancelled')
    },
  })

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ArtifactDataUIRegistration />
      {threadId ? <RestoreAgentState threadId={threadId} /> : null}
      {children}
    </AssistantRuntimeProvider>
  )
}

/**
 * Seeds the process panel's agent state from the persisted bootstrap exactly
 * once per thread mount (reload restoration). Only seeds when no interaction
 * has produced state yet this session.
 */
function RestoreAgentState({ threadId }: { threadId: string }) {
  const seeded = useRef(false)
  const setState = useAgUiSetState<Record<string, unknown>>()

  const { data: bootstrap } = useQuery({
    queryKey: ['thread-bootstrap', threadId],
    // RAW fetch here: wrapping this queryFn in the cache-backed
    // getThreadBootstrap() dedupes the query to its OWN in-flight promise
    // and deadlocks it forever (shown as the eternal "Loading conversation").
    queryFn: () => fetchBootstrap(threadId),
    retry: false,
  })

  useEffect(() => {
    if (!seeded.current && bootstrap?.agentState) {
      seeded.current = true
      setState(bootstrap.agentState)
    }
  }, [bootstrap, setState])

  return null
}
