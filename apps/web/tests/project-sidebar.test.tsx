import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ProjectSidebar } from '@/components/projects/project-sidebar'
import type { ReactNode } from 'react'

vi.mock('@/lib/api-client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api-client')>()
  return { ...original, apiFetch: vi.fn() }
})

import { apiFetch } from '@/lib/api-client'
import type { ProjectOut } from '@/features/projects/projects-api'
import type { ThreadOut } from '@/features/threads/threads-api'

const project: ProjectOut = {
  id: 'project_1',
  name: 'Workspace',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
}

const threads: ThreadOut[] = [
  {
    id: 'thread_a',
    projectId: 'project_1',
    title: 'First thread',
    status: 'active',
    lastRunId: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:01Z',
  },
  {
    id: 'thread_b',
    projectId: 'project_1',
    title: 'Second thread',
    status: 'active',
    lastRunId: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:02Z',
  },
]

function stubApi() {
  const mock = vi.mocked(apiFetch)
  mock.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/projects' && !init?.method) return [project]
    if (path === '/api/projects/project_1/threads' && !init?.method) return threads
    if (path === '/api/projects/project_1/threads' && init?.method === 'POST') {
      return { ...threads[0], id: 'thread_new', title: 'New conversation' }
    }
    if (path.startsWith('/api/threads/') && init?.method === 'DELETE') return undefined
    throw new Error(`unexpected apiFetch ${init?.method ?? 'GET'} ${path}`)
  })
  return mock
}

let locationProbe: { current: string }
function LocationProbe() {
  const location = useLocation()
  locationProbe.current = location.pathname
  return null
}

function SidebarHarness() {
  return (
    <>
      <LocationProbe />
      <ProjectSidebar />
    </>
  )
}

function setup(initialPath: string) {
  locationProbe = { current: initialPath }
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/" element={<SidebarHarness />} />
          <Route path="/projects/:projectId" element={<SidebarHarness />} />
          <Route
            path="/projects/:projectId/threads/:threadId"
            element={<SidebarHarness />}
          />
        </Routes>
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

describe('ProjectSidebar (live)', () => {
  it('renders projects with their threads', async () => {
    setup('/projects/project_1/threads/thread_a')

    expect(await screen.findByText('Workspace')).toBeInTheDocument()
    expect(await screen.findByText('First thread')).toBeInTheDocument()
    expect(screen.getByText('Second thread')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'New thread' }),
    ).toBeEnabled()
  })

  it('navigates to a thread on click', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    await user.click(await screen.findByText('Second thread'))
    await waitFor(() => {
      expect(locationProbe.current).toBe('/projects/project_1/threads/thread_b')
    })
  })

  it('marks the active thread with aria-current', async () => {
    setup('/projects/project_1/threads/thread_a')
    const active = await screen.findByRole('button', { name: 'First thread' })
    expect(active).toHaveAttribute('aria-current', 'page')
    expect(
      screen.getByRole('button', { name: 'Second thread' }),
    ).not.toHaveAttribute('aria-current')
  })

  it('creates a new thread and navigates to it', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    await user.click(await screen.findByRole('button', { name: 'New thread' }))
    await waitFor(() => {
      expect(locationProbe.current).toBe('/projects/project_1/threads/thread_new')
    })
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
      '/api/projects/project_1/threads',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('disables New thread when no project is in the URL', () => {
    setup('/')
    expect(screen.getByRole('button', { name: 'New thread' })).toBeDisabled()
  })

  it('deletes a thread and navigates back to the project', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    await screen.findByText('First thread')
    await user.click(
      screen.getByRole('button', { name: 'Thread actions: First thread' }),
    )
    await user.click(await screen.findByRole('menuitem', { name: /delete/i }))

    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/api/threads/thread_a', {
        method: 'DELETE',
      })
    })
    await waitFor(() => {
      expect(locationProbe.current).toBe('/projects/project_1')
    })
  })
})
