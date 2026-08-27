import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ProjectSidebar } from '@/components/projects/project-sidebar'

vi.mock('@/lib/api-client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api-client')>()
  return { ...original, apiFetch: vi.fn() }
})

import { apiFetch } from '@/lib/api-client'
import type { ProjectOut } from '@/features/projects/projects-api'
import type { ThreadOut } from '@/features/threads/threads-api'
import { mockViewport } from './setup'

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

function stubApi(threadList: ThreadOut[] = threads, projectId = project.id) {
  const mock = vi.mocked(apiFetch)
  mock.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/projects' && !init?.method) return [project]
    if (path === '/api/projects' && init?.method === 'POST') {
      const body = JSON.parse(init.body as string) as { name: string }
      return { ...project, id: 'project_new', name: body.name }
    }
    if (path === '/api/projects/project_1' && init?.method === 'PATCH') {
      const body = JSON.parse(init.body as string) as { name: string }
      return { ...project, name: body.name }
    }
    if (path === '/api/projects/project_1' && init?.method === 'DELETE') return undefined
    if (path === `/api/projects/${projectId}/threads` && !init?.method) return threadList
    if (path === `/api/projects/${projectId}/threads` && init?.method === 'POST') {
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
  it('fills the embedded desktop rail while preserving the mobile drawer width', async () => {
    setup('/projects/project_1/threads/thread_a')

    const wrapper = document.querySelector('[data-slot="sidebar-wrapper"]')
    expect(wrapper).toHaveStyle('--sidebar-width: 100%')
    expect(wrapper).toHaveStyle('--sidebar-width-mobile: 18rem')

    const activeThread = await screen.findByRole(
      'button',
      { name: 'First thread' },
      { timeout: 5000 },
    )
    expect(activeThread.className).toContain('w-full')

    cleanup()
    mockViewport({ mobile: true, compact: true })
    setup('/projects/project_1/threads/thread_a')
    const mobileWrapper = document.querySelector('[data-slot="sidebar-wrapper"]')
    expect(mobileWrapper).toHaveStyle('--sidebar-width-mobile: 18rem')
  })

  it('renders projects with their threads', async () => {
    setup('/projects/project_1/threads/thread_a')

    expect(await screen.findByText('Workspace')).toBeInTheDocument()
    expect(await screen.findByText('First thread')).toBeInTheDocument()
    expect(screen.getByText('Second thread')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'New thread' }),
    ).toBeEnabled()
  })

  it('reserves the project action slot and reveals actions on hover or focus', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    const projectLabel = await screen.findByRole('button', {
      name: 'Project: Workspace',
    })
    const actions = document.querySelector('[data-sidebar="group-actions"]')
    expect(actions).toBeInTheDocument()
    expect(actions).toHaveClass('pointer-events-none', 'opacity-0')
    expect(actions?.className).toContain('group-hover/group-header:opacity-100')
    expect(actions?.className).toContain(
      'group-focus-within/group-header:opacity-100',
    )
    expect(actions?.className).toContain('has-[[data-state=open]]:opacity-100')
    expect(projectLabel).toHaveClass('pe-[62px]')

    await user.hover(projectLabel)
    await user.click(
      screen.getByRole('button', { name: 'New thread in: Workspace' }),
    )
    expect(
      screen.getByRole('button', { name: 'New thread in: Workspace' }),
    ).toBeInTheDocument()
  })

  it('keeps the Fleet Agent switcher label and chevron in separate flex regions', async () => {
    setup('/projects/project_1/threads/thread_a')

    const trigger = await screen.findByRole('button', { name: 'Fleet Agent' })
    expect(trigger).toHaveClass('w-full', 'min-w-0')
    expect(trigger.querySelector('span.min-w-0.flex-1')).toBeInTheDocument()
    expect(trigger.querySelector('svg')).toHaveClass('ms-auto', 'shrink-0')
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

  it('toggles a project group via its collapsible trigger', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    // The group containing the active thread starts expanded.
    expect(await screen.findByText('First thread')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Project: Workspace' }))
    await waitFor(() => {
      expect(screen.queryByText('First thread')).not.toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Project: Workspace' }))
    expect(await screen.findByText('First thread')).toBeInTheDocument()
  })

  it('caps long thread lists at five behind a Show more expander', async () => {
    const user = userEvent.setup()
    const many: ThreadOut[] = Array.from({ length: 7 }, (_, i) => ({
      ...threads[0],
      id: `thread_${i + 1}`,
      title: `Thread ${i + 1}`,
      updatedAt: `2026-01-01T00:00:0${i + 1}Z`,
    }))
    stubApi(many)
    setup('/projects/project_1/threads/thread_1')

    expect(await screen.findByText('Thread 5')).toBeInTheDocument()
    expect(screen.queryByText('Thread 6')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Show more' }))
    expect(await screen.findByText('Thread 7')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Show less' }),
    ).toBeInTheDocument()
  })

  it('creates a new thread straight from the project row hover action', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    await user.click(
      await screen.findByRole('button', { name: 'New thread in: Workspace' }),
    )

    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/projects/project_1/threads',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    await waitFor(() => {
      expect(locationProbe.current).toBe('/projects/project_1/threads/thread_new')
    })
  })

  it('creates a project from the section "+" button via dialog', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    // Wait for the project list so the section-row button is mounted.
    await screen.findByRole('button', { name: 'Project: Workspace' })
    await user.click(screen.getByRole('button', { name: 'New project' }))
    const input = await screen.findByLabelText('Project name')
    await user.type(input, 'Fleet agent')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/projects',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ name: 'Fleet agent' }),
        }),
      )
    })
    await waitFor(() => {
      expect(locationProbe.current).toBe('/projects/project_new')
    })
  })

  it('renames a project through the row dropdown', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    await user.click(
      await screen.findByRole('button', { name: 'Project actions: Workspace' }),
    )
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }))

    const input = await screen.findByLabelText('Project name')
    expect(input).toHaveValue('Workspace')
    await user.clear(input)
    await user.type(input, 'Renamed workspace')
    await user.click(screen.getByRole('button', { name: 'Rename' }))

    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/projects/project_1',
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({ name: 'Renamed workspace' }),
        }),
      )
    })
  })

  it('deletes a project after confirmation and leaves it', async () => {
    const user = userEvent.setup()
    setup('/projects/project_1/threads/thread_a')

    await user.click(
      await screen.findByRole('button', { name: 'Project actions: Workspace' }),
    )
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }))

    // Destructive action needs explicit confirmation.
    await user.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/api/projects/project_1', {
        method: 'DELETE',
      })
    })
    await waitFor(() => {
      expect(locationProbe.current).toBe('/')
    })
  })

  it('shows the thread count badge on the project row', async () => {
    setup('/projects/project_1/threads/thread_a')

    // Badge renders once the project's threads have loaded.
    await screen.findByText('First thread')
    const badge = document.querySelector('[data-sidebar="menu-badge"]')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('2')
  })

  it('marks the active thread sub-button with data-active', async () => {
    setup('/projects/project_1/threads/thread_a')

    const active = await screen.findByRole('button', { name: 'First thread' })
    expect(active).toHaveAttribute('data-active')
    expect(active).toHaveAttribute('aria-current', 'page')
    expect(
      screen.getByRole('button', { name: 'Second thread' }),
    ).not.toHaveAttribute('data-active')
  })
})
