/**
 * The only module that depends on assistant-ui's history repository surface.
 * The server stores a versioned envelope so legacy AG-UI rows and exact
 * assistant-ui rows can coexist during migration.
 */

import {
  ExportedMessageRepository,
  type ExportedMessageRepositoryItem,
  useAuiState,
} from '@assistant-ui/react'
import { fromAgUiMessages } from '@assistant-ui/react-ag-ui'
import { useEffect, useRef } from 'react'

import * as threadApi from '@/features/threads/threads-api'
import type {
  MessageStorageEntry,
  ThreadBootstrap,
} from '@/features/threads/threads-api'

export type UserMessagePersistedHandler = (
  message: ExportedMessageRepositoryItem['message'],
) => void | Promise<void>

type ReadonlyJSONValue =
  | null
  | boolean
  | number
  | string
  | readonly ReadonlyJSONValue[]
  | { readonly [key: string]: ReadonlyJSONValue }

const threadWriteBarriers = new Map<string, Promise<void>>()

export async function persistThreadHeadWithRetry(
  threadId: string,
  headId: string | null,
  options: {
    signal: AbortSignal
    isCurrent: () => boolean
    retryDelayMs?: number
    maxRetries?: number
  },
): Promise<boolean> {
  const retryDelayMs = options.retryDelayMs ?? 300
  const maxRetries = options.maxRetries ?? 3

  const waitBeforeRetry = async (): Promise<void> => {
    await new Promise<void>((resolve) => {
      let settled = false
      let timeout: ReturnType<typeof globalThis.setTimeout>
      const finish = () => {
        if (settled) return
        settled = true
        globalThis.clearTimeout(timeout)
        options.signal.removeEventListener('abort', onAbort)
        resolve()
      }
      const onAbort = () => finish()
      timeout = globalThis.setTimeout(finish, retryDelayMs)
      options.signal.addEventListener('abort', onAbort, { once: true })
      if (options.signal.aborted) finish()
    })
  }

  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    if (!options.isCurrent()) return false
    try {
      await waitForThreadHistoryWrites(threadId, { consumeFailure: false })
      if (!options.isCurrent()) return false
      await threadApi.persistThreadHead(threadId, headId, {
        signal: options.signal,
      })
      return options.isCurrent()
    } catch {
      if (!options.isCurrent() || attempt >= maxRetries) return false
      await waitBeforeRetry()
    }
  }
  return false
}

/**
 * Waits for the pending history write for a thread.
 *
 * Failed writes are rethrown. By default, a failed write is consumed so it
 * does not block subsequent history operations; set `consumeFailure` to
 * `false` to preserve the failed write.
 *
 * @param threadId - The thread whose pending write to await
 * @param options - Controls whether a failed write is removed
 * @throws The error from the pending history write
 */
export async function waitForThreadHistoryWrites(
  threadId: string,
  options: { consumeFailure?: boolean } = {},
): Promise<void> {
  const barrier = threadWriteBarriers.get(threadId)
  if (!barrier) return
  try {
    await barrier
  } catch (error) {
    // The run request consumes a failed barrier so one transient write error
    // cannot wedge the thread forever. Head synchronization only observes the
    // failure and must leave it for the run request to consume.
    if (
      options.consumeFailure !== false &&
      threadWriteBarriers.get(threadId) === barrier
    ) {
      threadWriteBarriers.delete(threadId)
    }
    throw error
  }
}

/**
 * Creates a history adapter for loading and persisting a thread's messages.
 *
 * @param threadId - The thread whose history is managed
 * @param suppliedBootstrap - Optional preloaded thread data used instead of fetching bootstrap data
 * @param options - Optional callbacks invoked after successful message persistence
 * @returns An adapter that loads, appends, and updates thread messages
 */
export function buildHistoryAdapter(
  threadId: string,
  suppliedBootstrap?: ThreadBootstrap,
  options: { onUserMessagePersisted?: UserMessagePersistedHandler } = {},
): {
  load: () => Promise<
    ExportedMessageRepository & { state?: ReadonlyJSONValue }
  >
  append: (item: ExportedMessageRepositoryItem) => Promise<void>
  update: (item: ExportedMessageRepositoryItem) => Promise<void>
} {
  let bootstrap = suppliedBootstrap
  let writes: Promise<void> = Promise.resolve()

  const enqueue = (operation: () => Promise<void>): Promise<void> => {
    const next = writes.then(operation)
    let barrier: Promise<void>
    barrier = next.then(
      () => {
        if (threadWriteBarriers.get(threadId) === barrier) {
          threadWriteBarriers.delete(threadId)
        }
      },
      (error: unknown) => {
        // Keep the rejected barrier until the current waiting send consumes
        // it or a later append replaces it; branch writes stay ordered.
        throw error
      },
    )
    void barrier.catch(() => undefined)
    threadWriteBarriers.set(threadId, barrier)
    writes = next.catch(() => undefined)
    return next
  }

  const load = async () => {
    // The route normally supplies bootstrap. The fallback is deliberately a
    // raw fetch so it cannot recurse into the same TanStack query key.
    bootstrap ??= await threadApi.fetchBootstrap(threadId)
    const storedRepository = bootstrap.messageRepository
    const legacy = storedRepository === undefined
    const entries = storedRepository
      ? storedRepository.messages
      : (bootstrap.messages ?? []).map((content, index, all) => ({
          id: String(content.id ?? `legacy-${index}`),
          // Legacy bootstrap rows are one linear conversation. Giving every
          // row a null parent makes assistant-ui treat them as sibling roots,
          // so chain each row to the preceding legacy entry.
          parentId:
            index > 0
              ? String(all[index - 1]?.id ?? `legacy-${index - 1}`)
              : null,
          format: 'ag-ui/v1' as const,
          content,
        }))
    const items = entries.map(decodeEntry)
    const repository = ExportedMessageRepository.fromBranchableArray(items, {
      headId: legacy
        ? (entries.at(-1)?.id ?? null)
        : (storedRepository?.headId ?? null),
    })
    // assistant-ui 0.15's branchable factory drops runConfig from its input
    // type/runtime. Reattach it to the exported items so edit/regenerate runs
    // retain their exact persisted configuration on the next load.
    const messages = repository.messages.map((item, index) => ({
      ...item,
      ...(items[index]?.runConfig ? { runConfig: items[index].runConfig } : {}),
    }))
    return {
      ...repository,
      messages,
      ...(bootstrap.agentState
        ? { state: bootstrap.agentState as unknown as ReadonlyJSONValue }
        : {}),
    }
  }

  const persist = (item: ExportedMessageRepositoryItem) =>
    enqueue(async () => {
      const message = item.message as unknown as Record<string, unknown>
      await threadApi.persistThreadMessage(threadId, String(message.id), {
        parentId: item.parentId,
        format: 'aui/v0',
        content: message,
        ...(item.runConfig
          ? { runConfig: item.runConfig as unknown as Record<string, unknown> }
          : {}),
      })
      await threadApi.invalidateThreadBootstrap(threadId)

      if (item.message.role === 'user') {
        // A title sync must never make a successful message write fail. The
        // callback runs only after the message has been accepted by the API,
        // while its own failure remains local to title enrichment.
        void Promise.resolve(options.onUserMessagePersisted?.(item.message)).catch(
          () => undefined,
        )
      }
    })

  return { load, append: persist, update: persist }
}

function decodeEntry(entry: MessageStorageEntry): {
  message: ExportedMessageRepositoryItem['message']
  parentId: string | null
  runConfig?: ExportedMessageRepositoryItem['runConfig']
} {
  const message =
    entry.format === 'aui/v0'
      ? stripReasoningParts(entry.content)
      : fromAgUiMessages([entry.content] as never, { showThinking: false })[0]
  return {
    message: message as ExportedMessageRepositoryItem['message'],
    parentId: entry.parentId,
    ...(entry.runConfig ? { runConfig: entry.runConfig as never } : {}),
  }
}

/** aui/v0 is already assistant-ui-shaped, so it bypasses fromAgUiMessages. */
function stripReasoningParts(message: Record<string, unknown>) {
  const content = message.content
  if (!Array.isArray(content)) return message
  const safeContent = content.filter((part) => {
    if (typeof part !== 'object' || part === null || Array.isArray(part)) {
      return true
    }
    return !Object.entries(part as Record<string, unknown>).some(
      ([key, value]) => {
        const normalizedKey = key.replace(/[^a-z0-9]/gi, '').toLowerCase()
        const normalizedValue =
          typeof value === 'string' ? value.replace(/[^a-z0-9]/gi, '').toLowerCase() : ''
        return (
          ['type', 'kind', 'parttype', 'contenttype'].includes(normalizedKey) &&
          ['reasoning', 'thought', 'thinking', 'chainofthought', 'analysis'].includes(
            normalizedValue,
          )
        )
      },
    )
  })
  return safeContent.length === content.length
    ? message
    : { ...message, content: safeContent }
}

/** Persist branch navigation without mirroring agent state into Zustand. */
export function HistoryHeadSync({
  threadId,
  initialHeadId,
}: {
  threadId: string
  initialHeadId: string | null
}) {
  const messages = useAuiState((state) => state.thread.messages)
  const isRunning = useAuiState((state) => state.thread.isRunning)
  const headId = messages.at(-1)?.id ?? null
  const lastPersisted = useRef<string | null | undefined>(initialHeadId)
  const pendingHead = useRef<string | null | undefined>(undefined)
  const desiredHead = useRef<string | null | undefined>(initialHeadId)
  const retryGeneration = useRef(0)
  const retryAbort = useRef<AbortController | null>(null)
  const loaded = useRef(false)

  useEffect(() => {
    return () => {
      retryGeneration.current += 1
      retryAbort.current?.abort()
      retryAbort.current = null
      pendingHead.current = undefined
    }
  }, [])

  useEffect(() => {
    // A branch can change while a run is still streaming. Invalidate the old
    // retry chain immediately, even though the new head is intentionally not
    // persisted until the run settles.
    if (desiredHead.current !== headId) {
      desiredHead.current = headId
      retryGeneration.current += 1
      retryAbort.current?.abort()
      retryAbort.current = null
      pendingHead.current = undefined
    }
    // Streaming adds the assistant message to runtime state before its
    // history write exists, so syncing mid-run would publish an unpersisted
    // id. Wait for the run to settle; the final effect run below persists
    // the settled branch head.
    if (isRunning) return
    // assistant-ui surfaces optimistic placeholder ids ("__optimistic__*")
    // before the real message id arrives; those never exist server-side.
    // Skip the sync (without publishing a transient null) until the real id
    // replaces the placeholder.
    if (typeof headId === "string" && headId.startsWith("__optimistic__")) {
      return
    }
    // assistant-ui starts with an empty in-memory repository while its first
    // adapter load is pending. Do not publish that transient null head over
    // the server-selected branch, including the empty-thread null -> null
    // case; wait until the restored path is visible.
    if (!loaded.current) {
      if (messages.length === 0) return
      loaded.current = true
    }
    if (
      lastPersisted.current === headId ||
      pendingHead.current === headId
    ) {
      return
    }
    const generation = retryGeneration.current
    const controller = new AbortController()
    retryAbort.current = controller
    pendingHead.current = headId
    // A streamed assistant message can appear in runtime state slightly
    // before its history-adapter write is enqueued, so the first head write
    // may observe an "unknown branch head" 409. Retry briefly; any later
    // branch change aborts and supersedes this generation.
    const isCurrent = () =>
      retryGeneration.current === generation &&
      pendingHead.current === headId &&
      !controller.signal.aborted
    void persistThreadHeadWithRetry(threadId, headId, {
      signal: controller.signal,
      isCurrent,
    }).then((persisted) => {
      if (persisted && isCurrent()) lastPersisted.current = headId
    })
      .finally(() => {
        if (isCurrent()) {
          pendingHead.current = undefined
          retryAbort.current = null
        }
      })
  }, [headId, initialHeadId, threadId, isRunning])
  return null
}
