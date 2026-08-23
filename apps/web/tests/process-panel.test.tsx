import { cleanup, render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ActivityTab } from '@/components/process-panel/activity-tab'
import { ArtifactsTab } from '@/components/process-panel/artifacts-tab'
import { RunMetricsLine } from '@/components/process-panel/run-metrics'
import { SourcesTab } from '@/components/process-panel/sources-tab'
import { ToolExecutionCard } from '@/components/process-panel/tool-execution-card'
import { useAutoOpenProcessPanel } from '@/components/process-panel/use-auto-open-process-panel'
import type { AgentWorkspaceState } from '@/contracts/generated'
import { useWorkspaceStore } from '@/state/workspace-store'

const baseSteps: AgentWorkspaceState['steps'] = [
  {
    id: 'step-understand',
    phase: 'understanding',
    title: 'Understanding the request',
    publicSummary: 'Request is a documentation question.',
    status: 'completed',
    startedAt: '2026-01-01T00:00:00Z',
    finishedAt: '2026-01-01T00:00:02Z',
    durationMs: 400,
    toolCallIds: [],
    sourceIds: [],
    artifactIds: [],
  },
  {
    id: 'step-research',
    phase: 'research',
    title: 'Searching the documentation',
    status: 'running',
    startedAt: '2026-01-01T00:00:02Z',
    toolCallIds: ['tc-1'],
    sourceIds: ['src-1', 'src-2'],
    artifactIds: [],
  },
]

const runningState: AgentWorkspaceState = {
  schemaVersion: 1,
  threadId: 't-1',
  run: {
    id: 'r-1',
    status: 'running',
    startedAt: '2026-01-01T00:00:00Z',
    activeStepId: 'step-research',
    toolCallCount: 1,
  },
  steps: baseSteps,
  decisions: [
    {
      id: 'd-1',
      title: 'Pick transport boundary',
      alternatives: ['Custom SSE', 'AG-UI'],
      selected: 'AG-UI',
      publicRationale: 'Keeps the frontend decoupled from DSPy internals.',
      status: 'accepted',
    },
  ],
  toolCalls: [
    {
      id: 'tc-1',
      name: 'search_docs',
      status: 'completed',
      inputPreview: 'query="agent state"',
      outputPreview: 'Found 3 relevant documents.',
      startedAt: '2026-01-01T00:00:02Z',
      finishedAt: '2026-01-01T00:00:03Z',
      durationMs: 550,
    },
  ],
  sources: [
    {
      id: 'src-1',
      title: 'AG-UI — Events',
      sourceType: 'web',
      uri: 'https://docs.ag-ui.com/sdk/python/core/events',
      excerpt: 'State deltas apply JSON Patch updates.',
      toolCallId: 'tc-1',
    },
    {
      id: 'src-2',
      title: 'assistant-ui — Agent state',
      sourceType: 'web',
      uri: 'https://www.assistant-ui.com/docs/runtimes/ag-ui/agent-state',
      excerpt: 'useAgUiState mirrors agent state.',
      toolCallId: 'tc-1',
    },
  ],
  artifacts: [],
  metrics: { toolCallCount: 1 },
}

const completedState: AgentWorkspaceState = {
  ...runningState,
  run: {
    ...runningState.run,
    status: 'completed',
    finishedAt: '2026-01-01T00:00:04Z',
    terminationReason: 'submit',
  },
  steps: [
    ...baseSteps,
    {
      id: 'step-synthesis',
      phase: 'synthesis',
      title: 'Preparing the response',
      status: 'completed',
      finishedAt: '2026-01-01T00:00:04Z',
      durationMs: 750,
      toolCallIds: [],
      sourceIds: [],
      artifactIds: [],
    },
  ].map((step) =>
    step.id === 'step-research' ? { ...step, status: 'completed' } : step,
  ),
  metrics: {
    durationMs: 1900,
    inputTokens: 1250,
    outputTokens: 320,
    totalTokens: 1570,
    toolCallCount: 1,
    modelCallCount: 2,
  },
}

const failedState: AgentWorkspaceState = {
  ...runningState,
  run: {
    ...runningState.run,
    status: 'failed',
    finishedAt: '2026-01-01T00:00:01Z',
    terminationReason: 'forced_submit',
    errorCode: 'agent_no_output',
  },
  metrics: { durationMs: 900, toolCallCount: 0 },
}

const cancelledState: AgentWorkspaceState = {
  ...runningState,
  run: { ...runningState.run, status: 'cancelled' },
}

beforeEach(() => {
  localStorage.clear()
  useWorkspaceStore.setState({
    sidebarCollapsed: false,
    processPanelOpen: true,
    processPanelTab: 'activity',
    processPanelAutoOpened: false,
    sidebarSheetOpen: false,
    processSheetOpen: false,
  })
})

afterEach(cleanup)

describe('RunMetricsLine', () => {
  it('does not crash when an older snapshot contains null token usage', () => {
    const malformedMetrics = {
      durationMs: 900,
      toolCallCount: 0,
      totalTokens: null,
    } as unknown as AgentWorkspaceState['metrics']

    render(<RunMetricsLine metrics={malformedMetrics} />)

    expect(screen.getByLabelText('run metrics')).toHaveTextContent('0 tools')
    expect(screen.getByLabelText('run metrics')).not.toHaveTextContent('tokens')
  })
})

describe('ActivityTab', () => {
  it('renders running state with the active step highlighted', () => {
    render(<ActivityTab state={runningState} isRunning />)

    expect(screen.getByText('Running')).toBeInTheDocument()
    const activeStep = screen.getByRole('article', {
      name: 'step: Searching the documentation',
    })
    expect(activeStep.className).toContain('border-primary/40')

    // Running status icon is rendered (motion-safe only).
    expect(
      document.querySelector('[data-running="true"]'),
    ).toBeInTheDocument()
  })

  it('renders completed state with metrics and a quiet termination note', () => {
    render(<ActivityTab state={completedState} isRunning={false} />)

    expect(screen.getByText('Completed normally')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(
      screen.getByLabelText('run metrics').textContent,
    ).toContain('1.9s')
    expect(screen.getByLabelText('run metrics').textContent).toContain(
      '1,570 tokens',
    )
  })

  it('renders failed state as an alert with the public error code', () => {
    render(<ActivityTab state={failedState} isRunning={false} />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('agent_no_output')).toBeInTheDocument()
  })

  it('renders cancelled runs without alarming chrome', () => {
    render(<ActivityTab state={cancelledState} isRunning={false} />)
    expect(screen.getByText('Cancelled')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('expands the active step to show tools and evidence', () => {
    render(<ActivityTab state={runningState} isRunning />)

    const activeStep = screen.getByRole('article', {
      name: 'step: Searching the documentation',
    })
    expect(activeStep.textContent).toContain('search_docs')
    expect(activeStep.textContent).toContain('AG-UI — Events')
  })

  it('renders caveats when the run produced them', () => {
    const withCaveats: AgentWorkspaceState = {
      ...completedState,
      caveats: [
        'The answer was summarized from partial progress and may be incomplete.',
      ],
    }
    render(<ActivityTab state={withCaveats} isRunning={false} />)
    expect(screen.getByLabelText('Caveats')).toBeInTheDocument()
    expect(
      screen.getByText(/summarized from partial progress/),
    ).toBeInTheDocument()
  })

  it('renders decisions with the selected alternative marked', () => {
    render(<ActivityTab state={runningState} isRunning />)
    expect(screen.getByText(/AG-UI · selected/)).toBeInTheDocument()
    expect(screen.getByText(/Custom SSE/)).toBeInTheDocument()
  })
})

describe('ToolExecutionCard', () => {
  it('keeps long unbroken output from stretching the panel', () => {
    const longTool = {
      id: 'tc-long',
      name: 'search_docs',
      status: 'completed' as const,
      outputPreview: `${'x'.repeat(500)}`,
    }
    render(<ToolExecutionCard tool={longTool} />)
    const preview = screen.getByText(/out:/).parentElement as HTMLElement
    expect(preview.className).toContain('break-all')
    expect(preview.className).toContain('line-clamp-2')
  })

  it('surfaces tool errors in destructive text with no stack traces', () => {
    render(
      <ToolExecutionCard
        tool={{
          id: 'tc-fail',
          name: 'search_docs',
          status: 'failed',
          errorMessage: 'The documentation lookup timed out.',
        }}
      />,
    )
    expect(
      screen.getByText('The documentation lookup timed out.'),
    ).toBeInTheDocument()
  })
})

describe('SourcesTab', () => {
  it('renders an empty state', () => {
    render(<SourcesTab sources={[]} />)
    expect(screen.getByText('No sources yet.')).toBeInTheDocument()
  })

  it('renders sources with open links and copies citations', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })

    render(<SourcesTab sources={runningState.sources} />)

    expect(screen.getByText('AG-UI — Events')).toBeInTheDocument()
    const openLink = screen.getByRole('link', {
      name: 'open source: AG-UI — Events',
    })
    expect(openLink).toHaveAttribute('target', '_blank')
    expect(openLink).toHaveAttribute('rel', 'noreferrer')

    await user.click(
      screen.getByRole('button', { name: 'copy citation: AG-UI — Events' }),
    )
    expect(writeText).toHaveBeenCalledWith(
      '[AG-UI — Events](https://docs.ag-ui.com/sdk/python/core/events)',
    )
  })
})

describe('ArtifactsTab', () => {
  const artifacts: AgentWorkspaceState['artifacts'] = [
    {
      id: 'a-1',
      name: 'comparison-report.md',
      mediaType: 'text/markdown',
      sizeBytes: 2048,
      downloadUrl: '/api/artifacts/a-1',
      status: 'ready',
    },
    {
      id: 'a-2',
      name: 'diagram.svg',
      mediaType: 'image/svg+xml',
      status: 'generating',
    },
    {
      id: 'a-3',
      name: 'raw-data.csv',
      mediaType: 'text/csv',
      status: 'failed',
    },
  ]

  it('renders generation states and only offers downloads for ready artifacts', () => {
    render(<ArtifactsTab artifacts={artifacts} />)

    expect(screen.getByText('comparison-report.md')).toBeInTheDocument()
    expect(screen.getByText(/2\.0 KB/)).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'download artifact: comparison-report.md' }),
    ).toHaveAttribute('href', 'http://localhost:8000/api/artifacts/a-1')

    expect(screen.getByText('Generating')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'download artifact: diagram.svg' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'download artifact: raw-data.csv' }),
    ).not.toBeInTheDocument()
  })
})

describe('useAutoOpenProcessPanel', () => {
  function Probe() {
    const [count, setCount] = useState(0)
    Probe.setCount = setCount
    useAutoOpenProcessPanel(count)
    return null
  }
  Probe.setCount = (_: number) => {}

  it('opens the panel once on the first tool call (desktop only)', async () => {
    // Desktop viewport is the mockViewport() default.
    useWorkspaceStore.getState().setProcessPanelOpen(false)
    render(<Probe />)

    // First tool call: auto-open once.
    act(() => Probe.setCount(1))
    await vi.waitFor(() => {
      expect(useWorkspaceStore.getState().processPanelOpen).toBe(true)
      expect(useWorkspaceStore.getState().processPanelAutoOpened).toBe(true)
    })

    // Later tool calls must not re-open the panel after the user closes it.
    useWorkspaceStore.getState().setProcessPanelOpen(false)
    act(() => Probe.setCount(2))
    // The hook only ever fires on the 0 -> >0 transition.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(useWorkspaceStore.getState().processPanelOpen).toBe(false)
  })
})
