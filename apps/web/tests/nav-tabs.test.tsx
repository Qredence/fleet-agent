import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api-client')>()
  return { ...original, apiFetch: vi.fn() }
})

import { apiFetch } from '@/lib/api-client'
import { ProjectNavTabs } from '@/components/layout/project-nav-tabs'
import { OptimizerRoute } from '@/app/routes/optimizer-route'
import { ToolsRoute } from '@/app/routes/tools-route'
import { ConnectorsRoute } from '@/app/routes/connectors-route'
import { AgentRuntimeProvider } from '@/features/agent-runtime/agent-runtime-provider'

const project = {
  id: 'project_1',
  name: 'Workspace',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
}

const threads = [
  {
    id: 'thread_a',
    projectId: 'project_1',
    title: 'First thread',
    status: 'active',
    lastRunId: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:01Z',
  },
]

function stubApi() {
  const mock = vi.mocked(apiFetch)
  mock.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/projects' && !init?.method) return [project]
    if (path === '/api/projects/project_1/threads' && !init?.method) return threads
    if (path === '/api/threads/thread_a/bootstrap') {
      return {
        messages: [],
        agentState: null,
      }
    }
    return []
  })
  return mock
}

function renderWithProviders(ui: React.ReactElement, initialRoute = '/projects/project_1') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <AgentRuntimeProvider>
          {ui}
        </AgentRuntimeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  stubApi()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ProjectNavTabs & Workspace Secondary Views', () => {
  it('renders navigation tabs for project views', () => {
    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectNavTabs />} />
      </Routes>,
      '/projects/project_1'
    )

    expect(screen.getByRole('link', { name: /workspace/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /optimizer/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /tools/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /connectors/i })).toBeInTheDocument()
  })

  it('renders the Optimizer studio route', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectId/optimizer" element={<OptimizerRoute />} />
      </Routes>,
      '/projects/project_1/optimizer'
    )

    expect(await screen.findByRole('main', { name: /optimizer studio/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run GEPA Optimization/i })).toBeInTheDocument()
    expect(screen.getByText('FlexModule')).toBeInTheDocument()
  })

  it('renders the Tools catalog route', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectId/tools" element={<ToolsRoute />} />
      </Routes>,
      '/projects/project_1/tools'
    )

    expect(await screen.findByRole('main', { name: /tools catalog/i })).toBeInTheDocument()
    expect(screen.getByText('search_docs')).toBeInTheDocument()
    expect(screen.getByText('write_report')).toBeInTheDocument()
  })

  it('renders the Connectors hub route', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectId/connectors" element={<ConnectorsRoute />} />
      </Routes>,
      '/projects/project_1/connectors'
    )

    expect(await screen.findByRole('main', { name: /connectors hub/i })).toBeInTheDocument()
    expect(screen.getByText('GitHub MCP Server')).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL Lakebase MCP')).toBeInTheDocument()
  })
})
