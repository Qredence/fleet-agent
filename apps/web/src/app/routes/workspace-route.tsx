import { Navigate, useParams } from 'react-router-dom'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { AgentRuntimeProvider } from '@/features/agent-runtime/agent-runtime-provider'
import { useThreads } from '@/features/threads/use-threads'

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

  // Unknown thread id for this project → bounce to the project page.
  if (threadId && threads.isSuccess && !thread) {
    return <Navigate to={`/projects/${projectId}`} replace />
  }

  return (
    <AgentRuntimeProvider key={threadId ?? 'none'} threadId={threadId}>
      <AgentWorkspace
        projectId={projectId}
        threadId={threadId}
        threadTitle={thread?.title ?? 'New conversation'}
      />
    </AgentRuntimeProvider>
  )
}
