import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ToolCatalogEntry } from '@/features/tools/tools-api'
import { mockViewport } from './setup'

const mocks = vi.hoisted(() => ({
  useTools: vi.fn(),
  useOpenRouterAuth: vi.fn(),
  refetch: vi.fn(),
  signOut: vi.fn(),
}))

vi.mock('@/features/tools/use-tools', () => ({ useTools: () => mocks.useTools() }))
vi.mock('@/features/threads/use-threads', () => ({ useThreads: () => ({ data: [] }) }))
vi.mock('@/features/providers/use-openrouter-auth', () => ({ useOpenRouterAuth: () => mocks.useOpenRouterAuth() }))
vi.mock('@/components/workspace/agent-workspace', () => ({
  AgentWorkspace: ({ customMain }: { customMain: ReactNode }) => <main>{customMain}</main>,
}))
vi.mock('@/features/providers/components/openrouter-button', () => ({
  OpenRouterButton: ({ children }: { children: ReactNode }) => <button>{children}</button>,
}))
vi.mock('@/features/providers/settings/settings-dialog', () => ({
  SettingsDialog: ({ open }: { open: boolean }) => open ? <div role="dialog" aria-label="Settings" /> : null,
}))

import { ToolsRoute } from '@/app/routes/tools-route'
import { ConnectorsRoute } from '@/app/routes/connectors-route'
import { OptimizerRoute } from '@/app/routes/optimizer-route'

const entries: ToolCatalogEntry[] = [
  { name: 'search_docs', description: 'Search documents', capability: 'retrieval', read_only: true, idempotent: true, parallelizable: true, timeout_seconds: 30, requires_approval: false },
  { name: 'write_report', description: 'Write a report', capability: 'artifact', read_only: false, idempotent: false, parallelizable: false, timeout_seconds: 60, requires_approval: true },
]

function renderPage(page: ReactNode) {
  return render(
    <MemoryRouter initialEntries={['/projects/project_1']}>
      <Routes><Route path="/projects/:projectId" element={page} /></Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockViewport()
  mocks.useTools.mockReturnValue({ data: entries, isPending: false, isError: false, refetch: mocks.refetch })
  mocks.useOpenRouterAuth.mockReturnValue({ apiKey: '', isAuthenticated: false, signOut: mocks.signOut, selectedModel: '', customModelEnabled: false })
})

describe('Fluid workspace pages', () => {
  it('filters the live tool catalog without hiding mutation tools by default', async () => {
    const user = userEvent.setup()
    renderPage(<ToolsRoute />)
    expect(screen.getByRole('heading', { level: 2, name: 'DSPy Tools Catalog' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'search_docs' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'write_report' })).toBeInTheDocument()
    screen.getByRole('switch', { name: 'Read-only tools' }).focus()
    await user.keyboard(' ')
    expect(screen.getByRole('heading', { name: 'search_docs' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'write_report' })).not.toBeInTheDocument()
  })

  it('shows loading, retryable error, and filtered empty states', async () => {
    const user = userEvent.setup()
    mocks.useTools.mockReturnValue({ data: undefined, isPending: true, isError: false, refetch: mocks.refetch })
    const page = renderPage(<ToolsRoute />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading tools')
    mocks.useTools.mockReturnValue({ data: undefined, isPending: false, isError: true, refetch: mocks.refetch })
    page.rerender(<MemoryRouter initialEntries={['/projects/project_1']}><Routes><Route path="/projects/:projectId" element={<ToolsRoute />} /></Routes></MemoryRouter>)
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the tool registry')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(mocks.refetch).toHaveBeenCalledOnce()
    mocks.useTools.mockReturnValue({ data: [], isPending: false, isError: false, refetch: mocks.refetch })
    page.rerender(<MemoryRouter initialEntries={['/projects/project_1']}><Routes><Route path="/projects/:projectId" element={<ToolsRoute />} /></Routes></MemoryRouter>)
    expect(screen.getByRole('status')).toHaveTextContent('No tools are registered')
  })

  it('keeps the live OpenRouter actions separate from sample connectors', async () => {
    const user = userEvent.setup()
    const page = renderPage(<ConnectorsRoute />)
    expect(screen.getByRole('heading', { level: 2, name: 'Connectors & MCP Hub' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect OpenRouter' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Add Connector' })).toBeDisabled()
    expect(screen.getAllByText('Sample · not connected')).toHaveLength(3)
    expect(screen.getAllByText(/Sample latency:/)).toHaveLength(3)
    expect(screen.getAllByRole('button', { name: 'Configure' }).every((button) => button.hasAttribute('disabled'))).toBe(true)

    mocks.useOpenRouterAuth.mockReturnValue({ apiKey: 'sk-test-1234567890', isAuthenticated: true, signOut: mocks.signOut, selectedModel: 'model-1', customModelEnabled: true })
    page.rerender(<MemoryRouter initialEntries={['/projects/project_1']}><Routes><Route path="/projects/:projectId" element={<ConnectorsRoute />} /></Routes></MemoryRouter>)
    const openRouter = screen.getByRole('heading', { name: 'OpenRouter AI Gateway' }).closest('[data-slot="card"]')!
    expect(within(openRouter as HTMLElement).getByText('Connected')).toBeInTheDocument()
    await user.click(within(openRouter as HTMLElement).getByRole('button', { name: 'Configure' }))
    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeInTheDocument()
    await user.click(within(openRouter as HTMLElement).getByRole('button', { name: 'Disconnect' }))
    expect(mocks.signOut).toHaveBeenCalledOnce()
  })

  it('labels optimizer data as samples and keeps the action unavailable', () => {
    const { container } = renderPage(<OptimizerRoute />)
    expect(screen.getByRole('heading', { level: 2, name: /DSPy Program Optimizer/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run GEPA Optimization' })).toBeDisabled()
    expect(screen.getAllByText('Sample metric')).toHaveLength(2)
    expect(screen.getByText('Sample program · not generated from this project')).toBeInTheDocument()
    expect(container.querySelector('pre')).toHaveClass('overflow-x-auto')
  })

  it('uses one card column at mobile width', () => {
    mockViewport({ mobile: true, compact: true })
    const { container } = renderPage(<ConnectorsRoute />)
    expect(container.querySelector('[data-slot="card-group"]')).toHaveStyle({ gridTemplateColumns: 'repeat(1, minmax(0, 1fr))' })
  })
})
