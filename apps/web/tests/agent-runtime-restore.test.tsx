import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Deadlock regression (the eternal "Loading conversation" bug):
 * RestoreAgentState must resolve bootstraps via the RAW fetch, never via the
 * cache-backed getThreadBootstrap — the cache wrapper dedupes this queryFn
 * back to its own in-flight query and hangs forever.
 */

const fetchBootstrapMock = vi.fn()
const getThreadBootstrapMock = vi.fn()

vi.mock('@/features/threads/threads-api', () => ({
  fetchBootstrap: (...args: unknown[]) => fetchBootstrapMock(...args),
  getThreadBootstrap: (...args: unknown[]) => getThreadBootstrapMock(...args),
  invalidateThreadBootstrap: vi.fn(),
  listThreads: vi.fn(async () => []),
  createThread: vi.fn(),
  renameThread: vi.fn(),
  deleteThread: vi.fn(),
}))

import { AgentRuntimeProvider } from '@/features/agent-runtime/agent-runtime-provider'

const bootstrap = {
  thread: {
    id: 't-1',
    projectId: 'p-1',
    title: 'T',
    status: 'active',
    lastRunId: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  },
  messages: [],
  agentState: null,
  latestRun: null,
}

beforeEach(() => {
  fetchBootstrapMock.mockResolvedValue(bootstrap)
  getThreadBootstrapMock.mockResolvedValue(bootstrap)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('RestoreAgentState deadlock guard', () => {
  it('resolves bootstraps via the raw fetchBootstrap in RestoreAgentState', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AgentRuntimeProvider threadId="t-1">
          <p>child</p>
        </AgentRuntimeProvider>
      </QueryClientProvider>,
    )
    await waitFor(() => {
      // RestoreAgentState's own query calls the RAW fetch (the deadlock
      // pattern deadlocked the thread forever when this was cache-backed).
      expect(fetchBootstrapMock).toHaveBeenCalledWith('t-1')
    })
  })
})
