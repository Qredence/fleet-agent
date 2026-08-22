import { apiFetch } from '@/lib/api-client'
import { queryClient } from '@/lib/query-client'

export interface ThreadOut {
  id: string
  projectId: string
  title: string
  status: string
  lastRunId: string | null
  createdAt: string
  updatedAt: string
}

export interface ThreadBootstrap {
  thread: ThreadOut
  /** AG-UI wire messages, oldest first. */
  messages: Record<string, unknown>[]
  /** Latest AgentWorkspaceState snapshot for the panel, or null. */
  agentState: Record<string, unknown> | null
  latestRun: {
    id: string
    status: string
    terminationReason: string | null
    errorCode: string | null
  } | null
}

export function listThreads(projectId: string): Promise<ThreadOut[]> {
  return apiFetch<ThreadOut[]>(`/api/projects/${projectId}/threads`)
}

export function createThread(projectId: string, title = 'New conversation'): Promise<ThreadOut> {
  return apiFetch<ThreadOut>(`/api/projects/${projectId}/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export function fetchBootstrap(threadId: string): Promise<ThreadBootstrap> {
  return apiFetch<ThreadBootstrap>(`/api/threads/${threadId}/bootstrap`)
}

/** Cached bootstrap for components + the assistant-thread adapter. */
export function getThreadBootstrap(threadId: string): Promise<ThreadBootstrap> {
  return queryClient.fetchQuery({
    queryKey: ['thread-bootstrap', threadId],
    queryFn: () => fetchBootstrap(threadId),
  })
}

export function invalidateThreadBootstrap(threadId: string): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: ['thread-bootstrap', threadId] })
}

export function renameThread(threadId: string, title: string): Promise<ThreadOut> {
  return apiFetch<ThreadOut>(`/api/threads/${threadId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export async function deleteThread(threadId: string): Promise<void> {
  await apiFetch<void>(`/api/threads/${threadId}`, { method: 'DELETE' })
}
