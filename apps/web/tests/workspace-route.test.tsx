import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const routeMocks = vi.hoisted(() => ({
  fetchBootstrap: vi.fn(),
  listThreads: vi.fn(),
  renameThread: vi.fn(),
  onUserMessagePersisted:
    undefined as ((message: unknown) => void | Promise<void>) | undefined,
}))

vi.mock('@/features/agent-runtime/agent-runtime-provider', () => ({
  AgentRuntimeProvider: ({
    children,
    onUserMessagePersisted,
  }: {
    children: ReactNode
    onUserMessagePersisted?: (message: unknown) => void | Promise<void>
  }) => {
    routeMocks.onUserMessagePersisted = onUserMessagePersisted
    return children
  },
}))

vi.mock('@/components/workspace/agent-workspace', () => ({
  AgentWorkspace: ({ threadTitle }: { threadTitle: string }) => (
    <div data-testid="workspace-title">{threadTitle}</div>
  ),
}))

vi.mock('@/features/threads/threads-api', () => ({
  fetchBootstrap: (...args: unknown[]) => routeMocks.fetchBootstrap(...args),
  listThreads: (...args: unknown[]) => routeMocks.listThreads(...args),
  renameThread: (...args: unknown[]) => routeMocks.renameThread(...args),
}))

import { WorkspaceRoute } from '@/app/routes/workspace-route'
import type { ThreadBootstrap, ThreadOut } from '@/features/threads/threads-api'

const placeholderThread: ThreadOut = {
  id: 'thread_a',
  projectId: 'project_1',
  title: 'New conversation',
  status: 'active',
  lastRunId: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
}

const bootstrap: ThreadBootstrap = {
  schemaVersion: 1,
  thread: placeholderThread,
  messageRepository: { headId: null, messages: [] },
  messages: [],
  agentState: null,
  latestRun: null,
}

let queryClient: QueryClient

function renderRoute() {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/projects/project_1/threads/thread_a']}>
        <Routes>
          <Route
            path="/projects/:projectId/threads/:threadId"
            element={<WorkspaceRoute />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  routeMocks.listThreads.mockResolvedValue([placeholderThread])
  routeMocks.fetchBootstrap.mockResolvedValue(bootstrap)
  routeMocks.renameThread.mockResolvedValue({
    ...placeholderThread,
    title: 'Explain the project',
  })
  routeMocks.onUserMessagePersisted = undefined
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('WorkspaceRoute automatic thread titles', () => {
  it('renames the placeholder after the first accepted user message and updates route cache state', async () => {
    renderRoute()

    expect(await screen.findByTestId('workspace-title')).toHaveTextContent(
      'New conversation',
    )
    await waitFor(() =>
      expect(routeMocks.onUserMessagePersisted).toBeTypeOf('function'),
    )

    const handler = routeMocks.onUserMessagePersisted
    await act(async () => {
      await handler?.({
        id: 'user-1',
        role: 'user',
        content: [{ type: 'text', text: '  Explain   the project  ' }],
      })
    })

    expect(routeMocks.renameThread).toHaveBeenCalledWith(
      'thread_a',
      'Explain the project',
    )
    expect(
      queryClient.getQueryData<ThreadOut[]>([
        'projects',
        'project_1',
        'threads',
      ])?.[0]?.title,
    ).toBe('Explain the project')
    expect(await screen.findByTestId('workspace-title')).toHaveTextContent(
      'Explain the project',
    )

    await act(async () => {
      await handler?.({
        id: 'user-1',
        role: 'user',
        content: [{ type: 'text', text: 'Explain the project again' }],
      })
      await handler?.({
        id: 'assistant-1',
        role: 'assistant',
        content: [{ type: 'text', text: 'The answer' }],
      })
    })
    expect(routeMocks.renameThread).toHaveBeenCalledTimes(1)
  })

  it('does not rename a thread with an explicit title', async () => {
    const namedThread = { ...placeholderThread, title: 'Design notes' }
    routeMocks.listThreads.mockResolvedValue([namedThread])
    routeMocks.fetchBootstrap.mockResolvedValue({
      ...bootstrap,
      thread: namedThread,
    })

    renderRoute()
    expect(await screen.findByTestId('workspace-title')).toHaveTextContent(
      'Design notes',
    )
    await waitFor(() =>
      expect(routeMocks.onUserMessagePersisted).toBeTypeOf('function'),
    )

    await act(async () => {
      await routeMocks.onUserMessagePersisted?.({
        id: 'user-1',
        role: 'user',
        content: [{ type: 'text', text: 'Do not overwrite this title' }],
      })
    })

    expect(routeMocks.renameThread).not.toHaveBeenCalled()
  })
})
