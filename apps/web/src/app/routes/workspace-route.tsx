import { Navigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { AgentRuntimeProvider } from '@/features/agent-runtime/agent-runtime-provider'
import { useThreads } from '@/features/threads/use-threads'
import { fetchBootstrap } from '@/features/threads/threads-api'

/**
 * Workspace route. URL owns the active project/thread; the runtime provider
 * remounts (keyed by threadId) so every thread gets a clean adapter instance.
 */
export function WorkspaceRoute() {
  const { projectId, threadId } = useParams<{
    projectId: string
    threadId?: string
  }>()

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
    >
      <AgentWorkspace
        projectId={projectId}
        threadId={threadId}
        threadTitle={thread?.title ?? 'New conversation'}
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
