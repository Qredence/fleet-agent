import { useCallback, useRef } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { AgentRuntimeProvider } from '@/features/agent-runtime/agent-runtime-provider'
import type { UserMessagePersistedHandler } from '@/features/threads/assistant-thread-adapter'
import {
  DEFAULT_THREAD_TITLE,
  deriveThreadTitle,
  getUserMessageText,
} from '@/features/threads/thread-title'
import { useThreads } from '@/features/threads/use-threads'
import {
  fetchBootstrap,
  renameThread,
  type ThreadBootstrap,
  type ThreadOut,
} from '@/features/threads/threads-api'

/**
 * Manages the project workspace route and active conversation state, including thread loading, title resolution, and unknown-thread redirects.
 *
 * @returns The workspace view, a loading or error state, or a redirect for an unknown thread.
 */
export function WorkspaceRoute() {
  const { projectId, threadId } = useParams<{
    projectId: string
    threadId?: string
  }>()

  const queryClient = useQueryClient()
  const threads = useThreads(projectId)
  const thread = threadId
    ? threads.data?.find((candidate) => candidate.id === threadId)
    : undefined
  const bootstrap = useQuery({
    queryKey: ['thread-bootstrap', threadId],
    queryFn: () => fetchBootstrap(threadId as string),
    enabled: Boolean(threadId),
    retry: false,
  })
  const knownTitles = [thread?.title, bootstrap.data?.thread.title].filter(
    (title): title is string => Boolean(title),
  )
  // Bootstrap is authoritative for the active thread when the project list
  // is briefly stale. Prefer either source's explicit title over the
  // placeholder so automatic enrichment can never overwrite a named thread.
  const threadTitle =
    knownTitles.find((title) => title !== DEFAULT_THREAD_TITLE) ??
    knownTitles[0] ??
    DEFAULT_THREAD_TITLE
  const titleRenameAttempts = useRef(new Set<string>())
  const handleUserMessagePersisted = useCallback<UserMessagePersistedHandler>(
    async (message) => {
      if (!threadId || threadTitle !== DEFAULT_THREAD_TITLE) return
      if (titleRenameAttempts.current.has(threadId)) return

      const nextTitle = deriveThreadTitle(getUserMessageText(message))
      if (nextTitle === DEFAULT_THREAD_TITLE) return

      // Mark before the request so rerenders, retries, and assistant messages
      // cannot issue a second automatic rename for this thread.
      titleRenameAttempts.current.add(threadId)

      try {
        const updatedThread = await renameThread(threadId, nextTitle)
        queryClient.setQueryData<ThreadOut[] | undefined>(
          ['projects', projectId, 'threads'],
          (current) =>
            current?.map((candidate) =>
              candidate.id === updatedThread.id ? updatedThread : candidate,
            ),
        )
        queryClient.setQueryData<ThreadBootstrap | undefined>(
          ['thread-bootstrap', threadId],
          (current) =>
            current
              ? {
                  ...current,
                  thread: { ...current.thread, title: updatedThread.title },
                }
              : current,
        )
      } catch {
        // The accepted message remains successful if title enrichment fails.
        // The per-thread guard also prevents a retry loop from firing PATCHes.
      }
    },
    [projectId, queryClient, threadId, threadTitle],
  )

  // Unknown thread id for this project → bounce to the project page.
  if (threadId && threads.isSuccess && !thread) {
    return <Navigate to={`/projects/${projectId}`} replace />
  }

  if (threadId && bootstrap.isPending) {
    return <WorkspaceLoading />
  }

  if (threadId && bootstrap.isError) {
    return (
      <section className="flex min-h-screen items-center justify-center p-6">
        <div className="max-w-md space-y-3 text-center">
          <h1 className="text-lg font-semibold">Unable to restore this thread</h1>
          <p className="text-sm text-muted-foreground">
            The conversation could not be loaded. Retry before starting a new run.
          </p>
          <button
            type="button"
            className="rounded-md border px-3 py-2 text-sm"
            onClick={() => void bootstrap.refetch()}
          >
            Retry
          </button>
        </div>
      </section>
    )
  }

  return (
    <AgentRuntimeProvider
      key={threadId ?? 'none'}
      threadId={threadId}
      bootstrap={bootstrap.data}
      onUserMessagePersisted={handleUserMessagePersisted}
    >
      <AgentWorkspace
        projectId={projectId}
        threadId={threadId}
        threadTitle={threadTitle}
      />
    </AgentRuntimeProvider>
  )
}

function WorkspaceLoading() {
  return (
    <section className="flex min-h-screen items-center justify-center p-6">
      <p className="text-sm text-muted-foreground">Loading conversation…</p>
    </section>
  )
}
