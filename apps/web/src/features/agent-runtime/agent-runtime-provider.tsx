import { HttpAgent } from '@ag-ui/client'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { useAgUiRuntime } from '@assistant-ui/react-ag-ui'
import { useEffect, useMemo, type ReactNode } from 'react'

import {
  buildHistoryAdapter,
  HistoryHeadSync,
  waitForThreadHistoryWrites,
} from '@/features/threads/assistant-thread-adapter'
import { ArtifactDataUIRegistration } from '@/features/artifacts/artifact-data-ui'
import type { ThreadBootstrap } from '@/features/threads/threads-api'

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
 * messages and the supplied bootstrap state seeds the process panel.
 */
export function AgentRuntimeProvider({
  threadId,
  bootstrap,
  children,
}: {
  threadId?: string
  bootstrap?: ThreadBootstrap
  children: ReactNode
}) {
  const agent = useMemo(
    () =>
      new HttpAgent({
        url: AGENT_URL,
        fetch: async (url, requestInit) => {
          if (
            threadId &&
            requestInit.method?.toUpperCase() === 'POST' &&
            url.includes('/api/agent')
          ) {
            await waitForThreadHistoryWrites(threadId)
          }
          return fetch(url, requestInit)
        },
        ...(API_KEY ? { headers: { 'X-API-Key': API_KEY } } : {}),
      }),
    [threadId],
  )

  // Bind the agent's wire threadId to the URL thread. Without this the client
  // invents a fresh id and engine mode 404s (runs belong to persisted threads).
  useEffect(() => {
    if (threadId) {
      agent.threadId = threadId
    }
  }, [agent, threadId])

  const adapters = useMemo(
    () =>
      threadId
        ? { history: buildHistoryAdapter(threadId, bootstrap) }
        : undefined,
    // Bootstrap is fetched before this keyed provider mounts. Keep the
    // adapter identity stable after mount so cache invalidation from an
    // append/update cannot trigger a second runtime load.
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
      {threadId ? (
        <HistoryHeadSync
          threadId={threadId}
          initialHeadId={bootstrap?.messageRepository?.headId ?? null}
        />
      ) : null}
      {children}
    </AssistantRuntimeProvider>
  )
}
