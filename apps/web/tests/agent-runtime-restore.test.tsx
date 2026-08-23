import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Restoration regression: the runtime must use the route-supplied bootstrap
 * snapshot and its fallback adapter load must use the raw fetch.
 */

const fetchBootstrapMock = vi.fn()
const persistThreadHeadMock = vi.fn()

vi.mock('@/features/threads/threads-api', () => ({
  fetchBootstrap: (...args: unknown[]) => fetchBootstrapMock(...args),
  invalidateThreadBootstrap: vi.fn(),
  persistThreadHead: (...args: unknown[]) => persistThreadHeadMock(...args),
  persistThreadMessage: vi.fn(),
  listThreads: vi.fn(async () => []),
  createThread: vi.fn(),
  renameThread: vi.fn(),
  deleteThread: vi.fn(),
}))

import { AgentRuntimeProvider } from '@/features/agent-runtime/agent-runtime-provider'

const bootstrap = {
  schemaVersion: 1,
  thread: {
    id: 't-1',
    projectId: 'p-1',
    title: 'T',
    status: 'active',
    lastRunId: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  },
  messageRepository: { headId: null, messages: [] },
  messages: [],
  agentState: null,
  latestRun: null,
}

beforeEach(() => {
  fetchBootstrapMock.mockResolvedValue(bootstrap)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('thread restoration bootstrap', () => {
  it('uses the supplied bootstrap without issuing a second bootstrap query', async () => {
    render(
      <AgentRuntimeProvider threadId="t-1" bootstrap={bootstrap}>
        <p>child</p>
      </AgentRuntimeProvider>,
    )
    await new Promise((resolve) => setTimeout(resolve, 25))
    expect(fetchBootstrapMock).not.toHaveBeenCalled()
    expect(persistThreadHeadMock).not.toHaveBeenCalled()
  })

  it('resolves fallback adapter loads via raw fetchBootstrap', async () => {
    render(
      <AgentRuntimeProvider threadId="t-1">
        <p>child</p>
      </AgentRuntimeProvider>,
    )
    await waitFor(() => {
      // The adapter fallback calls the RAW fetch (the deadlock pattern
      // deadlocked the thread forever when this was cache-backed).
      expect(fetchBootstrapMock).toHaveBeenCalledWith('t-1')
    })
  })
})
