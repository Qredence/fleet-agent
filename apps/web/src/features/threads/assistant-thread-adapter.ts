/**
 * The ONLY module in the app that depends on assistant-ui's experimental
 * adapter/history surfaces. Everything else speaks to plain
 * `ThreadBootstrap` from features/threads/threads-api.ts.
 *
 * Restoration strategy (deliberate, given the experimental status):
 * - messages arrive in AG-UI wire format and convert via
 *   `fromAgUiMessages(…, {showThinking: false})` to match the runtime,
 * - thread switching is `remount-per-thread` (the provider is keyed by
 *   threadId at the route level), NOT the unstable threadList adapter,
 * - the panel state snapshot is seeded once per mount from bootstrap.agentState
 *   via `useAgUiSetState`,
 * - `append` is an explicit no-op: the backend persists messages at run
 *   boundaries (see services/run_persistence.py), so client-side persistence
 *   would only duplicate rows — documented as safe in the runtime options.
 *
 * ROOT-CAUSE GUARD: TanStack-query-backed helpers (`getThreadBootstrap`,
 * `fetchQuery`) must NEVER be called from inside another queryFn that shares
 * the same queryKey — the query dedupes to its OWN in-flight promise and
 * deadlocks forever ("Loading conversation"). See agent-runtime-provider.
 */

import { ExportedMessageRepository } from '@assistant-ui/react'
import { fromAgUiMessages } from '@assistant-ui/react-ag-ui'

import { getThreadBootstrap } from '@/features/threads/threads-api'

export function buildHistoryAdapter(threadId: string): {
  load: () => Promise<ExportedMessageRepository>
  append: () => Promise<void>
} {
  return {
    async load() {
      const bootstrap = await getThreadBootstrap(threadId)
      return ExportedMessageRepository.fromArray(
        fromAgUiMessages(bootstrap.messages as never, { showThinking: false }),
      )
    },
    async append() {
      // No-op by design: the backend persists messages on run completion.
    },
  }
}
