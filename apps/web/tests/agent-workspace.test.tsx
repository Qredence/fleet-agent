import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { AgentRuntimeProvider } from '@/features/agent-runtime/agent-runtime-provider'
import { useWorkspaceStore } from '@/state/workspace-store'
import { mockViewport } from './setup'

function renderWorkspace(ui: ReactElement = <AgentWorkspace />) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AgentRuntimeProvider>{ui}</AgentRuntimeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const storeDefaults = {
  sidebarCollapsed: false,
  processPanelOpen: true,
  processPanelTab: 'activity',
  sidebarSheetOpen: false,
  processSheetOpen: false,
} as const

beforeEach(() => {
  localStorage.clear()
  useWorkspaceStore.setState(storeDefaults)
  mockViewport()
})

afterEach(cleanup)

describe('AgentWorkspace — wide desktop', () => {
  it('renders sidebar, conversation, and process panes', () => {
    renderWorkspace()

    expect(
      screen.getByRole('complementary', { name: /projects and threads/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('main', { name: /conversation/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('complementary', { name: /^process$/i }),
    ).toBeInTheDocument()
  })

  it('switches process panel tabs', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('tab', { name: 'Sources' }))
    expect(
      screen.getByText(/sources the agent consults will appear here/i),
    ).toBeInTheDocument()
    expect(useWorkspaceStore.getState().processPanelTab).toBe('sources')

    await user.click(screen.getByRole('tab', { name: 'Artifacts' }))
    expect(
      screen.getByText(/generated artifacts will appear here/i),
    ).toBeInTheDocument()
  })

  it('exposes the selected file through an honest process header', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)

    renderWorkspace(
      <AgentWorkspace
        projectId="project_1"
        threadId="thread_a"
        threadTitle="First thread"
      />,
    )

    expect(screen.getByRole('heading', { name: 'Process' })).toBeInTheDocument()
    expect(
      screen.getByLabelText('fleet-agent, README.md'),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /copy path README\.md/i }))
    expect(writeText).toHaveBeenCalledWith('README.md')
    expect(await screen.findByRole('status')).toHaveTextContent(
      'README.md copied to clipboard.',
    )

    await user.click(screen.getByRole('button', { name: 'Open README.md' }))
    expect(open).toHaveBeenCalledWith('/README.md', '_blank')

    await user.click(screen.getByRole('tab', { name: 'Artifacts' }))
    await user.click(await screen.findByRole('button', { name: /^PLAN\.md/ }))
    expect(
      screen.getByRole('button', { name: 'Open unavailable for this file' }),
    ).toBeDisabled()

    open.mockRestore()
  })

  it('hides the process panel via its close button and reopens via header toggle', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(
      screen.getByRole('button', { name: /close process panel/i }),
    )
    expect(useWorkspaceStore.getState().processPanelOpen).toBe(false)
    expect(
      screen.queryByRole('complementary', { name: /^process$/i }),
    ).not.toBeInTheDocument()

    const toggle = screen.getByRole('button', {
      name: /toggle process panel/i,
    })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    await user.click(toggle)
    expect(useWorkspaceStore.getState().processPanelOpen).toBe(true)
    expect(
      screen.getByRole('complementary', { name: /^process$/i }),
    ).toBeInTheDocument()
  })

  it('collapses the sidebar via the header toggle', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('button', { name: /toggle sidebar/i }))
    expect(useWorkspaceStore.getState().sidebarCollapsed).toBe(true)
    expect(
      screen.queryByRole('complementary', { name: /projects and threads/i }),
    ).not.toBeInTheDocument()
  })

  it('renders keyboard-focusable resize handles', () => {
    const { container } = renderWorkspace()
    const handles = container.querySelectorAll('[data-slot="resizable-handle"]')
    expect(handles.length).toBeGreaterThan(0)
    for (const handle of handles) {
      expect(handle).toHaveAttribute('role', 'separator')
      expect(handle).toHaveAttribute('tabindex', '0')
    }
  })

  it('renders a live composer wired to the AG-UI runtime', () => {
    renderWorkspace()
    const input = screen.getByRole('textbox', { name: /message input/i })
    expect(input).toBeEnabled()
  })

  it('persists panel preferences to localStorage', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('tab', { name: 'Artifacts' }))

    const persisted = JSON.parse(
      localStorage.getItem('fleet-agent-workspace') ?? '{}',
    ) as { state: Record<string, unknown> }
    expect(persisted.state.processPanelTab).toBe('artifacts')
    expect(persisted.state).not.toHaveProperty('sidebarSheetOpen')
    expect(persisted.state).not.toHaveProperty('processSheetOpen')
  })
})

describe('AgentWorkspace — mobile', () => {
  beforeEach(() => mockViewport({ mobile: true, compact: true }))

  it('renders neither pane inline, only the conversation', () => {
    renderWorkspace()

    expect(
      screen.queryByRole('complementary', { name: /projects and threads/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('complementary', { name: /^process$/i }),
    ).not.toBeInTheDocument()
    expect(screen.getByLabelText(/conversation/i)).toBeInTheDocument()
  })

  it('opens the sidebar sheet and returns focus to its trigger on close', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    const trigger = screen.getByRole('button', { name: /toggle sidebar/i })
    await user.click(trigger)
    trigger.focus()

    await screen.findByRole('dialog', { name: /projects and threads/i })

    await user.keyboard('{Escape}')
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: /projects and threads/i }),
      ).not.toBeInTheDocument(),
    )
    expect(trigger).toHaveFocus()
  })

  it('opens the process sheet and closes it from the panel header', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(
      screen.getByRole('button', { name: /toggle process panel/i }),
    )
    await screen.findByRole('dialog', { name: /^process$/i })

    const moreActions = screen.getByRole('button', {
      name: 'More process actions',
    })
    expect(moreActions).toBeInTheDocument()
    await user.click(moreActions)
    expect(
      await screen.findByRole('menuitem', { name: /^Copy path$/i }),
    ).toBeInTheDocument()

    await user.click(
      screen.getByRole('button', { name: /close process panel/i }),
    )
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: /^process$/i }),
      ).not.toBeInTheDocument(),
    )
  })
})

describe('AgentWorkspace — compact sheet', () => {
  beforeEach(() => mockViewport({ compact: true }))

  it('keeps process actions in an overflow menu', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(
      screen.getByRole('button', { name: /toggle process panel/i }),
    )
    await screen.findByRole('dialog', { name: /^process$/i })

    expect(
      screen.queryByRole('button', { name: /copy path/i }),
    ).not.toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: 'More process actions' }),
    )
    expect(
      await screen.findByRole('menuitem', { name: /^Copy path$/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('menuitem', { name: /Open in new tab/i }),
    ).toBeInTheDocument()
  })
})
