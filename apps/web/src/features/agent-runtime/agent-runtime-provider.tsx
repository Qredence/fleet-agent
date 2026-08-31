import { HttpAgent } from '@ag-ui/client'
import {
  AssistantRuntimeProvider,
  CompositeAttachmentAdapter,
  type FeedbackAdapter,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
} from '@assistant-ui/react'
import { useAgUiRuntime } from '@assistant-ui/react-ag-ui'
import { useEffect, useMemo, useRef, type ReactNode } from 'react'

import {
  buildHistoryAdapter,
  HistoryHeadSync,
  type UserMessagePersistedHandler,
  waitForThreadHistoryWrites,
} from '@/features/threads/assistant-thread-adapter'
import { AgUiRuntimePresenceProvider } from '@/features/agent-runtime/ag-ui-presence'
import { ArtifactDataUIRegistration } from '@/features/artifacts/artifact-data-ui'
import { InlineAgentDataUIRegistration } from '@/features/agent-runtime/inline-agent-data-ui'
import type { ThreadBootstrap } from '@/features/threads/threads-api'
import { getAgentProviderHeaders } from '@/lib/providers'

const AGENT_URL = `${
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
}/api/agent`
const AGENT_PATHNAME = new URL(AGENT_URL).pathname

function isAgentRunRequest(url: string | URL, requestInit: RequestInit): boolean {
  if (requestInit.method?.toUpperCase() !== 'POST') return false
  try {
    // Compare against the agent URL's own pathname so path-prefixed API
    // base URLs (e.g. VITE_API_BASE_URL="https://host/fleet") still match.
    return new URL(String(url), AGENT_URL).pathname === AGENT_PATHNAME
  } catch {
    return String(url)
      .split('?', 1)[0]
      .endsWith(AGENT_PATHNAME)
  }
}

/** Add browser-owned provider headers only to the agent POST request. */
export function createAgentFetch(
  threadId?: string,
): (url: string, requestInit: RequestInit) => Promise<Response> {
  return async (url, requestInit) => {
    const isAgentRequest = isAgentRunRequest(url, requestInit)
    if (threadId && isAgentRequest) {
      await waitForThreadHistoryWrites(threadId)
    }
    const headers = new Headers(requestInit.headers)
    if (isAgentRequest) {
      // Browser-owned provider profile headers (BYOK): only ever attached to
      // the agent run POST, never to other Fleet API resources.
      const providerHeaders = getAgentProviderHeaders()
      for (const [k, v] of Object.entries(providerHeaders)) {
        headers.set(k, v)
      }
    }
    return fetch(url, { ...requestInit, headers })
  }
}

const API_KEY: string | undefined = import.meta.env.VITE_API_KEY || undefined

// Attachments stay local to the assistant-ui runtime. The simple adapters
// provide picker/drop previews and convert supported files into message parts
// at send time; no upload endpoint or persistence is involved.
const attachmentAdapter = new CompositeAttachmentAdapter([
  new SimpleImageAttachmentAdapter(),
  new SimpleTextAttachmentAdapter(),
])

// Message feedback is tracked in memory only: the backend has no feedback
// endpoint yet, so thumbs state lives for the current session and resets on
// reload. Swap in a persistent adapter when feedback storage lands.
const feedbackByMessageId = new Map<string, 'positive' | 'negative'>()

const feedbackAdapter: FeedbackAdapter = {
  submit: ({ message, type }) => {
    feedbackByMessageId.set(message.id, type)
  },
}

/**
 * Provides the AG-UI runtime for a workspace conversation.
 *
 * @param threadId - The persisted conversation identifier.
 * @param bootstrap - Initial state used to restore the conversation.
 * @param onUserMessagePersisted - Callback invoked after a user message is persisted.
 * @param children - Content rendered within the runtime provider.
 * @returns The runtime provider containing the workspace content.
 */
export function AgentRuntimeProvider({
  threadId,
  bootstrap,
  onUserMessagePersisted,
  children,
}: {
  threadId?: string
  bootstrap?: ThreadBootstrap
  onUserMessagePersisted?: UserMessagePersistedHandler
  children: ReactNode
}) {
  const onUserMessagePersistedRef = useRef(onUserMessagePersisted)

  useEffect(() => {
    onUserMessagePersistedRef.current = onUserMessagePersisted
  }, [onUserMessagePersisted])

  const agent = useMemo(
    () =>
      new HttpAgent({
        url: AGENT_URL,
        fetch: createAgentFetch(threadId),
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
    () => ({
      attachments: attachmentAdapter,
      feedback: feedbackAdapter,
      ...(threadId
        ? {
            history: buildHistoryAdapter(threadId, bootstrap, {
              onUserMessagePersisted: (message) =>
                onUserMessagePersistedRef.current?.(message),
            }),
          }
        : {}),
    }),
    // Bootstrap is fetched before this keyed provider mounts. Keep the
    // adapter identity stable after mount so cache invalidation from an
    // append/update cannot trigger a second runtime load.
    [threadId],
  )

  const runtime = useAgUiRuntime({
    agent,
    showThinking: false,
    adapters,
    unstable_enableMessageQueue: true,
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
      <AgUiRuntimePresenceProvider>
        <ArtifactDataUIRegistration />
        <InlineAgentDataUIRegistration />
        {threadId ? (
          <HistoryHeadSync
            threadId={threadId}
            initialHeadId={bootstrap?.messageRepository?.headId ?? null}
          />
        ) : null}
        {children}
      </AgUiRuntimePresenceProvider>
    </AssistantRuntimeProvider>
  )
}
