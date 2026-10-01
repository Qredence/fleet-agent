import type { AgentWorkspaceState } from '@/contracts/generated'
import type {
  MessageRepository,
  MessageStorageEntry,
  ThreadBootstrap as ThreadBootstrapEnvelope,
  ThreadOut,
} from '@/contracts/thread-bootstrap'
import { apiFetch, apiJsonFetch } from '@/lib/api-client'
import { queryClient } from '@/lib/query-client'

export const THREAD_BOOTSTRAP_SCHEMA_VERSION: ThreadBootstrapEnvelope['schemaVersion'] =
  1

export type { MessageStorageEntry, ThreadOut }

/**
 * The v1 bootstrap envelope from packages/contracts/thread-bootstrap.schema.json.
 * `messageRepository` is always present in current server responses, but
 * payloads written by older servers may lack it, so decoding tolerates its
 * absence; `agentState` is the generated AgentWorkspaceState model.
 */
export interface ThreadBootstrap
  extends Omit<ThreadBootstrapEnvelope, 'messageRepository' | 'agentState'> {
  messageRepository?: MessageRepository
  agentState: AgentWorkspaceState | null
}

export type MessageStorageFormat = 'ag-ui/v1' | 'aui/v0'

/**
 * A storage entry as this client writes it: the schema types `format` as a
 * plain string (the repository passes persisted values through untouched),
 * so the known-format union is pinned here and enforced by
 * `validateThreadBootstrap` below.
 */
export type MessageStorageItem = Omit<MessageStorageEntry, 'format'> & {
  format: MessageStorageFormat
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
  return apiJsonFetch<ThreadOut>(`/api/projects/${projectId}/threads`, 'POST', { title })
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
  item: Omit<MessageStorageItem, 'id'>,
): Promise<{ id: string }> {
  return apiJsonFetch<{ id: string }>(
    `/api/threads/${threadId}/messages/${encodeURIComponent(messageId)}`,
    'PUT',
    item,
  )
}

export function persistThreadHead(
  threadId: string,
  headId: string | null,
  init: Pick<RequestInit, 'signal'> = {},
): Promise<{ headId: string | null }> {
  return apiJsonFetch<{ headId: string | null }>(
    `/api/threads/${threadId}/history/head`,
    'PUT',
    { headId },
    init,
  )
}

export function renameThread(threadId: string, title: string): Promise<ThreadOut> {
  return apiJsonFetch<ThreadOut>(`/api/threads/${threadId}`, 'PATCH', { title })
}

export async function deleteThread(threadId: string): Promise<void> {
  await apiFetch<void>(`/api/threads/${threadId}`, { method: 'DELETE' })
}
