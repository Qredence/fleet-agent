import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ArtifactsTab } from '@/components/process-panel/artifacts-tab'
import { SourcesTab } from '@/components/process-panel/sources-tab'
import type { AgentWorkspaceState } from '@/contracts/generated'
import { useWorkspaceStore } from '@/state/workspace-store'

const state: AgentWorkspaceState = {
  schemaVersion: 1,
  threadId: 't-1',
  run: { id: 'r-1', status: 'completed', toolCallCount: 1 },
  steps: [],
  decisions: [],
  toolCalls: [
    {
      id: 'tc-1',
      name: 'search_docs',
      status: 'completed',
    },
  ],
  sources: [
    {
      id: 'src-1',
      title: 'AG-UI — Events',
      sourceType: 'web',
      uri: 'https://docs.ag-ui.com/sdk/python/core/events',
      excerpt: 'Deltas.',
      toolCallId: 'tc-1',
    },
  ],
  artifacts: [
    {
      id: 'a-1',
      name: 'state-sync-notes.md',
      mediaType: 'text/markdown',
      sizeBytes: 64,
      downloadUrl: '/api/artifacts/a-1',
      status: 'ready',
    },
  ],
  metrics: { toolCallCount: 1 },
}

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockResolvedValue(
    new Response(
      '# DSPy report\n\n**Actual Markdown content**\n\n- One useful finding\n\n[Official source](https://dspy.ai)',
      { headers: { 'content-type': 'text/markdown' } },
    ),
  )
  vi.stubGlobal('fetch', fetchMock)
  useWorkspaceStore.setState({
    selectedArtifactId: null,
    processPanelTab: 'activity',
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

describe('SourcesTab — originating tool', () => {
  it('shows which tool produced the source', () => {
    render(
      <SourcesTab
        sources={state.sources}
        toolNamesById={new Map([['tc-1', 'search_docs']])}
      />,
    )
    expect(screen.getByText(/via search_docs/)).toBeInTheDocument()
  })
})

describe('ArtifactsTab — selection + download URL', () => {
  it('renders the actual Markdown content for the selected artifact', async () => {
    render(<ArtifactsTab artifacts={state.artifacts} selectedArtifactId="a-1" />)

    expect(await screen.findByRole('heading', { name: 'DSPy report' })).toBeInTheDocument()
    expect(screen.getByText('Actual Markdown content')).toBeInTheDocument()
    expect(screen.getByText('One useful finding')).toBeInTheDocument()

    const source = screen.getByRole('link', { name: 'Official source' })
    expect(source).toHaveAttribute('href', 'https://dspy.ai/')
    expect(source).toHaveAttribute('target', '_blank')
    expect(source).toHaveAttribute('rel', 'noopener noreferrer')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/artifacts/a-1',
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: 'text/plain, text/markdown;q=0.9',
        }),
      }),
    )
  })

  it('resolves relative downloadUrl against the API base', () => {
    render(<ArtifactsTab artifacts={state.artifacts} />)
    const link = screen.getByRole('link', {
      name: 'download artifact: state-sync-notes.md',
    })
    expect(link).toHaveAttribute('href', 'http://localhost:8000/api/artifacts/a-1')
  })

  it('highlights the selected artifact', () => {
    render(
      <ArtifactsTab artifacts={state.artifacts} selectedArtifactId="a-1" />,
    )
    const card = screen.getByRole('article', { name: 'artifact: state-sync-notes.md' })
    expect(card).toHaveAttribute('aria-current', 'true')
    expect(card.className).toContain('border-primary/50')
  })

  it('does not highlight others', () => {
    render(
      <ArtifactsTab artifacts={state.artifacts} selectedArtifactId="a-999" />,
    )
    expect(
      screen.getByRole('article', { name: 'artifact: state-sync-notes.md' }),
    ).not.toHaveAttribute('aria-current')
  })
})

describe('workspace store — artifact selection', () => {
  it('tracks selection transiently', () => {
    useWorkspaceStore.getState().setSelectedArtifactId('a-1')
    expect(useWorkspaceStore.getState().selectedArtifactId).toBe('a-1')

    const persisted = JSON.parse(
      localStorage.getItem('fleet-agent-workspace') ?? '{}',
    ) as { state: Record<string, unknown> }
    expect(persisted.state.selectedArtifactId).toBeUndefined()
  })
})
