import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ArtifactsTab } from '@/features/process-panel/artifacts-tab'
import { ProcessStepCard } from '@/features/process-panel/process-step-card'
import { ProcessPanel } from '@/features/process-panel/process-panel'
import { RunMetricsLine } from '@/features/process-panel/run-metrics'
import { RunActivityInlineContent } from '@/features/process-panel/run-activity-inline'
import { SourcesTab } from '@/features/process-panel/sources-tab'
import { ToolExecutionCard } from '@/features/process-panel/tool-execution-card'
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

const synthesisStep: AgentWorkspaceState['steps'][number] = {
  id: 'step-synthesis',
  phase: 'synthesis',
  title: 'Preparing the response',
  status: 'completed',
  finishedAt: '2026-01-01T00:00:04Z',
  durationMs: 750,
  toolCallIds: [],
  sourceIds: [],
  artifactIds: [],
}

const completedState: AgentWorkspaceState = {
  ...runningState,
  run: {
    ...runningState.run,
    status: 'completed',
    finishedAt: '2026-01-01T00:00:04Z',
    terminationReason: 'submit',
  },
  steps: [...baseSteps, synthesisStep].map((step) =>
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

const synthesisState: AgentWorkspaceState = {
  ...completedState,
  run: { ...completedState.run, terminationReason: 'synthesis' },
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
    processPanelTab: 'sources',
    sidebarSheetOpen: false,
    processSheetOpen: false,
  })
})

afterEach(cleanup)

describe('ProcessStepCard', () => {
  it.each(['active', 'failed', 'details'] as const)(
    'opens when %s changes the preference and preserves manual toggles',
    async (change) => {
      const user = userEvent.setup()
      const initial = {
        step: baseSteps[1],
        tools: [],
        sourceTitles: change === 'details' ? [] : ['Evidence source'],
        isActive: change === 'details',
      }
      const { rerender } = render(<ProcessStepCard {...initial} />)
      expect(screen.getByRole('article')).not.toHaveAttribute('data-expanded')

      const updated = {
        ...initial,
        isActive: change !== 'failed',
        step: change === 'failed'
          ? { ...initial.step, status: 'failed' as const }
          : initial.step,
        sourceTitles: ['Evidence source'],
      }
      rerender(<ProcessStepCard {...updated} />)
      expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'true')

      await user.click(screen.getByRole('button'))
      rerender(<ProcessStepCard {...updated} sourceTitles={['Updated evidence']} />)
      expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'false')

      // Turning the preference off must also preserve a manually opened card.
      await user.click(screen.getByRole('button'))
      rerender(<ProcessStepCard {...updated} isActive={false}
        step={{ ...updated.step, status: 'completed' }} />)
      expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'true')
    },
  )
})

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

describe('RunActivityInlineContent', () => {
  // Content lives inside a collapsible that is closed once the run stops
  // streaming, so non-running cases expand it first, like a user would.
  async function renderActivity(
    state: AgentWorkspaceState | undefined,
    isRunning = false,
  ) {
    const user = userEvent.setup()
    render(<RunActivityInlineContent state={state} isRunning={isRunning} />)
    if (!isRunning) {
      await user.click(screen.getByRole('button', { name: /run activity/i }))
    }
  }

  it('renders nothing before the first run of the session', () => {
    const idleState: AgentWorkspaceState = {
      ...runningState,
      run: { id: 'r-2', status: 'idle', toolCallCount: 0 },
      steps: [],
      decisions: [],
      toolCalls: [],
      sources: [],
    }
    const { container } = render(
      <RunActivityInlineContent state={idleState} isRunning={false} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when there is no workspace state', () => {
    const { container } = render(
      <RunActivityInlineContent state={undefined} isRunning={false} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('collapses to a status summary when the run completes', async () => {
    render(<RunActivityInlineContent state={completedState} isRunning={false} />)

    const trigger = screen.getByRole('button', { name: /run activity/i })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(trigger).toHaveTextContent('Completed')
    expect(screen.queryByText('Completed normally')).not.toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(trigger)
    expect(screen.getByText('Completed normally')).toBeInTheDocument()
  })

  it('renders running state with the active step highlighted', async () => {
    await renderActivity(runningState, true)

    expect(screen.getByText('Running')).toBeInTheDocument()
    const activeStep = screen.getByRole('article', {
      name: 'step: Searching the documentation',
    })
    expect(activeStep).toHaveAttribute('data-active', 'true')

    // Running status icon is rendered (motion-safe only).
    expect(
      document.querySelector('[data-running="true"]'),
    ).toBeInTheDocument()
  })

  it('nests detailed tool cards under steps in the Process panel timeline', () => {
    render(
      <RunActivityInlineContent
        state={runningState}
        isRunning
        variant="panel"
        detailedTools
      />,
    )

    const activeStep = screen.getByRole('article', {
      name: 'step: Searching the documentation',
    })
    expect(activeStep).toHaveAttribute('data-expanded', 'true')
    // Linked tools live under the step — not a flat Tool calls dump.
    expect(
      within(activeStep).getByRole('article', { name: 'tool: search_docs' }),
    ).toBeInTheDocument()
    expect(within(activeStep).getByText('query="agent state"')).toBeInTheDocument()
    expect(
      within(activeStep).getByText('Found 3 relevant documents.'),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Tool calls')).not.toBeInTheDocument()
    // Route/decisions precede steps in the scannable timeline.
    const timeline = screen.getByLabelText('Process timeline')
    const route = within(timeline).getByLabelText('Route')
    const steps = within(timeline).getByLabelText('Steps')
    expect(
      timeline.compareDocumentPosition(route) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(route.compareDocumentPosition(steps) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('keeps detail-less steps quiet and hides sub-100ms durations', async () => {
    const quietState: AgentWorkspaceState = {
      ...completedState,
      steps: completedState.steps.map((step) =>
        step.id === 'step-synthesis' ? { ...step, durationMs: 2 } : step,
      ),
    }
    await renderActivity(quietState)

    const detailLess = screen.getByRole('article', {
      name: 'step: Understanding the request',
    })
    expect(within(detailLess).queryByRole('button')).not.toBeInTheDocument()
    // Meaningful durations still render on quiet rows.
    expect(within(detailLess).getByText('400ms')).toBeInTheDocument()

    const instant = screen.getByRole('article', {
      name: 'step: Preparing the response',
    })
    expect(within(instant).queryByRole('button')).not.toBeInTheDocument()
    expect(within(instant).queryByText('2ms')).not.toBeInTheDocument()
  })

  it('renders parallel child steps with their mixed tool statuses', async () => {
    const parallelState: AgentWorkspaceState = {
      ...runningState,
      run: { ...runningState.run, activeStepId: 'research-1', toolCallCount: 2 },
      steps: [
        ...baseSteps,
        {
          id: 'research-1',
          parentId: 'step-research',
          phase: 'research',
          title: 'Check the first source',
          status: 'running',
          toolCallIds: ['tc-1'],
          sourceIds: [],
          artifactIds: [],
        },
        {
          id: 'research-2',
          parentId: 'step-research',
          phase: 'research',
          title: 'Check the second source',
          status: 'failed',
          publicSummary: 'This task failed safely.',
          toolCallIds: ['tc-2'],
          sourceIds: [],
          artifactIds: [],
        },
      ],
      toolCalls: [
        ...runningState.toolCalls,
        {
          id: 'tc-2',
          name: 'web_search',
          status: 'failed',
          errorMessage: 'The web_search tool call failed.',
        },
      ],
    }

    await renderActivity(parallelState, true)

    const first = screen.getByRole('article', {
      name: 'step: Check the first source',
    }).parentElement
    const second = screen.getByRole('article', {
      name: 'step: Check the second source',
    }).parentElement
    expect(first).toHaveAttribute('data-parent-id', 'step-research')
    expect(first).toHaveAttribute('data-depth', '1')
    expect(first).toHaveStyle({ marginInlineStart: '16px' })
    expect(second).toHaveTextContent('This task failed safely.')
    expect(screen.getByText('The web_search tool call failed.')).toBeInTheDocument()
  })

  it('renders completed state with metrics and a quiet termination note', async () => {
    await renderActivity(completedState)

    expect(screen.getByText('Completed normally')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(
      screen.getByLabelText('run metrics').textContent,
    ).toContain('1.9s')
    expect(screen.getByLabelText('run metrics').textContent).toContain(
      '1,570 tokens',
    )
  })

  it('renders failed state as an alert with the public error message and code', async () => {
    await renderActivity(failedState)

    const alert = screen.getByRole('alert')
    expect(alert).toBeInTheDocument()
    expect(alert).toHaveTextContent(
      /finished without producing a final answer/i,
    )
    // forced_submit on a failed run is quieter context under the error message
    expect(alert).toHaveTextContent(/stopped early/i)
    expect(screen.getByText('agent_no_output')).toBeInTheDocument()
  })

  it('renders hard-stop terminations with the matching public error copy', async () => {
    const maxItersState: AgentWorkspaceState = {
      ...failedState,
      run: {
        ...failedState.run,
        terminationReason: 'max_iters',
        errorCode: 'agent_no_output',
      },
    }
    await renderActivity(maxItersState)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(
      /finished without producing a final answer/i,
    )
    expect(alert).toHaveTextContent(/iteration limit reached/i)
  })

  it('treats a successful forced_submit as amber caution, not a red alert', async () => {
    const forcedState: AgentWorkspaceState = {
      ...completedState,
      run: {
        ...completedState.run,
        terminationReason: 'forced_submit',
      },
      caveats: [
        'The agent was stopped before completing its process; the answer was summarized from partial progress and may be incomplete.',
      ],
    }
    await renderActivity(forcedState)

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    const notice = screen.getByRole('status')
    expect(notice).toHaveTextContent(/stopped early/i)
    expect(screen.getByLabelText('Caveats')).toBeInTheDocument()
  })

  it('treats the routed program synthesis ending as a normal completion', async () => {
    await renderActivity(synthesisState)

    expect(screen.getByText('Completed normally')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders cancelled runs without alarming chrome', async () => {
    await renderActivity(cancelledState)
    expect(screen.getByText('Cancelled')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('gracefully degrades unknown error codes to internal_error copy', async () => {
    const unknownErrorState: AgentWorkspaceState = {
      ...failedState,
      run: {
        ...failedState.run,
        errorCode: 'custom_unrecognized_code',
        terminationReason: undefined,
      },
    }
    await renderActivity(unknownErrorState)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('The agent run failed.')
    expect(screen.getByText('custom_unrecognized_code')).toBeInTheDocument()
    const icon = alert.querySelector('svg')
    expect(icon).toHaveAttribute('aria-hidden', 'true')
  })

  it('expands the active step to show tools and evidence', async () => {
    await renderActivity(runningState, true)

    const activeStep = screen.getByRole('article', {
      name: 'step: Searching the documentation',
    })
    expect(activeStep.textContent).toContain('search_docs')
    expect(activeStep.textContent).toContain('AG-UI — Events')
  })

  it('renders caveats when the run produced them', async () => {
    const withCaveats: AgentWorkspaceState = {
      ...completedState,
      caveats: [
        'The answer was summarized from partial progress and may be incomplete.',
      ],
    }
    await renderActivity(withCaveats)
    expect(screen.getByLabelText('Caveats')).toBeInTheDocument()
    expect(
      screen.getByText(/summarized from partial progress/),
    ).toBeInTheDocument()
  })

  it.each([
    ['alternatives', false, 'Route'],
    ['selection', false, 'Route'],
    ['title', false, 'Decisions'],
    ['alternatives', true, 'Route and decisions'],
    ['selection', true, 'Route and decisions'],
  ] as const)('labels %s decisions (mixed: %s)', (kind, mixed, heading) => {
    const titleOnly = {
      id: 'title-only', title: 'Use public sources',
      alternatives: [], status: 'accepted' as const,
    }
    const decision = kind === 'title' ? titleOnly : {
      ...runningState.decisions[0],
      alternatives: kind === 'selection' ? [] : ['AG-UI', 'Custom SSE'],
      selected: kind === 'selection' ? 'AG-UI' : undefined,
    }
    render(<RunActivityInlineContent
      state={{ ...runningState, decisions: mixed ? [decision, titleOnly] : [decision] }}
      isRunning variant="panel"
    />)
    const section = screen.getByRole('region', { name: heading })
    expect(within(section).getByRole('heading', { name: heading })).toBeInTheDocument()
    expect(within(section).getAllByRole('article')).toHaveLength(mixed ? 2 : 1)
  })

  it('renders decisions with the selected alternative marked', async () => {
    await renderActivity(runningState, true)
    expect(screen.getByLabelText('Route')).toBeInTheDocument()
    expect(
      screen.getByRole('article', { name: 'route: Pick transport boundary' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/AG-UI · selected/)).toBeInTheDocument()
    expect(screen.getByText(/Custom SSE/)).toBeInTheDocument()
  })

  it('expands failed steps by default and nests their tool errors', async () => {
    const failedStepState: AgentWorkspaceState = {
      ...runningState,
      run: { ...runningState.run, activeStepId: 'step-understand', toolCallCount: 1 },
      steps: [
        baseSteps[0],
        {
          id: 'step-research',
          phase: 'research',
          title: 'Searching the documentation',
          status: 'failed',
          publicSummary: 'Lookup failed safely.',
          toolCallIds: ['tc-1'],
          sourceIds: [],
          artifactIds: [],
        },
      ],
      toolCalls: [
        {
          id: 'tc-1',
          name: 'search_docs',
          status: 'failed',
          errorMessage: 'The documentation lookup timed out.',
        },
      ],
      decisions: [],
    }
    await renderActivity(failedStepState, true)

    const failedStep = screen.getByRole('article', {
      name: 'step: Searching the documentation',
    })
    expect(failedStep).toHaveAttribute('data-expanded', 'true')
    expect(
      within(failedStep).getByText('The documentation lookup timed out.'),
    ).toBeInTheDocument()
  })

  it('keeps unlinked tools in a residual Tool calls section', async () => {
    const orphanState: AgentWorkspaceState = {
      ...runningState,
      steps: [baseSteps[0]],
      toolCalls: [
        {
          id: 'tc-orphan',
          name: 'workspace_shell',
          status: 'completed',
          inputPreview: 'ls',
          outputPreview: 'ok',
          durationMs: 12,
        },
      ],
      decisions: [],
    }
    await renderActivity(orphanState, true)

    expect(screen.getByLabelText('Tool calls')).toBeInTheDocument()
    expect(
      screen.getByRole('article', { name: 'tool: workspace_shell' }),
    ).toHaveTextContent('ls')
  })

  it('places termination after steps in the timeline', async () => {
    await renderActivity(completedState)

    const timeline = screen.getByLabelText('Process timeline')
    const steps = within(timeline).getByLabelText('Steps')
    const notice = within(timeline).getByRole('status')
    expect(
      steps.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(notice).toHaveTextContent('Completed normally')
  })
})

describe('ProcessPanel', () => {
  // Rendered without AgUiRuntimePresenceProvider, so the presence context
  // defaults to false: the panel must render its full chrome without calling
  // any AG-UI hook (they throw without a mounted runtime).
  it('renders tabs and empty states without a runtime', async () => {
    const user = userEvent.setup()
    render(<ProcessPanel onClose={() => undefined} />)

    expect(screen.getByRole('heading', { name: 'Process' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Close process panel' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('tab', { name: 'Activity' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('tab', { name: 'Sources' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('tab', { name: 'Artifacts' }),
    ).toBeInTheDocument()

    // The active tab's body mounts; Base UI unmounts inactive panels.
    expect(screen.getByText('No sources discovered')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Activity' }))
    expect(screen.getByText('No activity yet')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Artifacts' }))
    expect(screen.getByText('No artifacts generated')).toBeInTheDocument()
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
    // Long unbroken output wraps to the terminal-block's horizontal-scroll
    // surface (`codeScroll` / `codeSurface`) rather than stretching the card.
    const block = screen.getByLabelText('Copy terminal contents').closest(
      '[data-slot="terminal-block"]',
    ) as HTMLElement
    expect(block).toBeInTheDocument()
    const scroller = block.querySelector('.overflow-x-auto') as HTMLElement
    expect(scroller).toBeInTheDocument()
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
    expect(screen.getByText('No sources discovered')).toBeInTheDocument()
    expect(
      screen.getByText('Sources referenced during agent runs will appear here.'),
    ).toBeInTheDocument()
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
