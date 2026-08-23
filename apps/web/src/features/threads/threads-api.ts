import type { AgentWorkspaceState } from '@/contracts/generated'
import { apiFetch } from '@/lib/api-client'
import { queryClient } from '@/lib/query-client'

export const THREAD_BOOTSTRAP_SCHEMA_VERSION = 1 as const

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
  schemaVersion: typeof THREAD_BOOTSTRAP_SCHEMA_VERSION
  thread: ThreadOut
  /** Branch repository in the current bootstrap format. */
  messageRepository?: {
    headId: string | null
    messages: MessageStorageEntry[]
  }
  /** Compatibility field for older consumers; use messageRepository. */
  messages: Record<string, unknown>[]
  /** Latest AgentWorkspaceState snapshot for the panel, or null. */
  agentState: AgentWorkspaceState | null
  latestRun: {
    id: string
    status: string
    terminationReason: string | null
    errorCode: string | null
  } | null
}

export type MessageStorageFormat = 'ag-ui/v1' | 'aui/v0'

export interface MessageStorageEntry {
  id: string
  parentId: string | null
  format: MessageStorageFormat
  content: Record<string, unknown>
  runConfig?: Record<string, unknown>
}

export class UnsupportedThreadBootstrapSchemaError extends Error {
  readonly schemaVersion: unknown

  constructor(schemaVersion: unknown) {
    super(
      `Unsupported thread bootstrap schema version: ${String(schemaVersion)}`,
    )
    this.name = 'UnsupportedThreadBootstrapSchemaError'
    this.schemaVersion = schemaVersion
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

/**
 * Decode only the bootstrap envelope versions this client understands.
 * Unknown versions must reach the route's retry UI instead of being treated as
 * the current shape and silently losing branch history.
 */
export function validateThreadBootstrap(payload: unknown): ThreadBootstrap {
  if (!isRecord(payload)) {
    throw new Error('Invalid thread bootstrap response.')
  }
  if (payload.schemaVersion !== THREAD_BOOTSTRAP_SCHEMA_VERSION) {
    throw new UnsupportedThreadBootstrapSchemaError(payload.schemaVersion)
  }
  if (!isRecord(payload.thread) || !Array.isArray(payload.messages)) {
    throw new Error('Invalid thread bootstrap response.')
  }
  const repository = payload.messageRepository
  if (repository !== undefined) {
    if (!isRecord(repository) || !Array.isArray(repository.messages)) {
      throw new Error('Invalid thread bootstrap message repository.')
    }
    for (const entry of repository.messages) {
      if (!isRecord(entry) || !isRecord(entry.content)) {
        throw new Error('Invalid thread bootstrap message repository.')
      }
      if (entry.format !== 'ag-ui/v1' && entry.format !== 'aui/v0') {
        throw new Error('Unsupported thread message format.')
      }
    }
  }
  return payload as unknown as ThreadBootstrap
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

export async function fetchBootstrap(threadId: string): Promise<ThreadBootstrap> {
  const payload = await apiFetch<unknown>(`/api/threads/${threadId}/bootstrap`)
  return validateThreadBootstrap(payload)
}

export function invalidateThreadBootstrap(threadId: string): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: ['thread-bootstrap', threadId] })
}

export function persistThreadMessage(
  threadId: string,
  messageId: string,
  item: Omit<MessageStorageEntry, 'id'>,
): Promise<{ id: string }> {
  return apiFetch<{ id: string }>(
    `/api/threads/${threadId}/messages/${encodeURIComponent(messageId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    },
  )
}

export function persistThreadHead(
  threadId: string,
  headId: string | null,
): Promise<{ headId: string | null }> {
  return apiFetch<{ headId: string | null }>(
    `/api/threads/${threadId}/history/head`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ headId }),
    },
  )
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
