import { useEffect, useMemo, useState } from 'react'

import { ChevronRightIcon } from 'lucide-react'

import { useAuiState } from '@assistant-ui/react'
import { useAgUiState } from '@assistant-ui/react-ag-ui'

import { DecisionCard } from '@/components/process-panel/decision-card'
import { ProcessStepCard } from '@/components/process-panel/process-step-card'
import {
  RunMetricsLine,
  TerminationNotice,
} from '@/components/process-panel/run-metrics'
import {
  StatusChip,
  formatDuration,
} from '@/components/process-panel/status-chip'
import { ToolExecutionCard } from '@/components/process-panel/tool-execution-card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { AgentWorkspaceState } from '@/contracts/generated'
import { useHasAgUiRuntime } from '@/features/agent-runtime/ag-ui-presence'
import { collapsePanel, mono } from '@/lib/surfaces'
import { cn } from '@/lib/utils'

/**
 * Renders the current (latest) agent run's sanitized activity inline, next to
 * the latest assistant message, inside the assistant-ui message tree.
 *
 * `AgentWorkspaceState` is live-only, per-thread, latest-run state: the card
 * always tracks the current run and renders nothing before the first run of
 * the session (restored threads carry no per-message workspace state).
 */
export function RunActivityInline() {
  const hasRuntime = useHasAgUiRuntime()
  const isLast = useAuiState((state) => state.message.isLast)
  const isRunning = useAuiState((state) => state.thread.isRunning)

  if (!hasRuntime || !isLast) return null
  return <RunActivityInlineSubscription isRunning={isRunning} />
}

/**
 * Subscribes to the AG-UI agent state. Split from {@link RunActivityInline}
 * so `useAgUiState` is only called under an AG-UI runtime (preview routes
 * have none, where the hook would throw).
 */
function RunActivityInlineSubscription({ isRunning }: { isRunning: boolean }) {
  const agentState = useAgUiState<AgentWorkspaceState>()
  return <RunActivityInlineContent state={agentState} isRunning={isRunning} />
}

/**
 * Presentational run-activity card. Prop-injected so tests (and future
 * callers) can drive it without a runtime.
 *
 * @param state - The sanitized agent workspace state for the latest run.
 * @param isRunning - Whether the agent run is currently streaming.
 */
export function RunActivityInlineContent({
  state,
  isRunning,
}: {
  state: AgentWorkspaceState | undefined
  isRunning: boolean
}) {
  const hasActivity =
    state !== undefined &&
    (state.run.status !== 'idle' ||
      state.steps.length > 0 ||
      state.decisions.length > 0 ||
      state.toolCalls.length > 0 ||
      (state.caveats?.length ?? 0) > 0)

  // Live elapsed clock: ticks once per second while the run is active so the
  // trigger shows real elapsed time instead of freezing at the last state
  // delta. Pauses (stops ticking) the moment the run settles.
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (!isRunning || !state?.run.startedAt) return
    setNowMs(Date.now())
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isRunning, state?.run.startedAt])

  // A run streams open and collapses to its summary when it settles; the
  // first manual toggle takes over for the rest of that run, and the next
  // run starts expanded again.
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  useEffect(() => {
    if (isRunning) setUserOpen(null)
  }, [isRunning])

  const toolNamesById = useMemo(
    () => new Map(state?.toolCalls.map((tool) => [tool.id, tool.name]) ?? []),
    [state?.toolCalls],
  )
  const sourceTitlesById = useMemo(
    () =>
      new Map(state?.sources.map((source) => [source.id, source.title]) ?? []),
    [state?.sources],
  )
  const stepDepthById = useMemo(() => {
    const steps = state?.steps ?? []
    const stepsById = new Map(steps.map((step) => [step.id, step]))
    const depths = new Map<string, number>()
    const depthOf = (id: string, visiting = new Set<string>()): number => {
      const cached = depths.get(id)
      if (cached !== undefined) return cached
      if (visiting.has(id)) return 0
      visiting.add(id)
      const parentId = stepsById.get(id)?.parentId
      const depth = parentId ? depthOf(parentId, visiting) + 1 : 0
      depths.set(id, depth)
      return depth
    }
    steps.forEach((step) => depthOf(step.id))
    return depths
  }, [state?.steps])

  if (!state || !hasActivity) return null

  const duration =
    isRunning && state.run.startedAt
      ? formatDuration(Math.max(0, nowMs - Date.parse(state.run.startedAt)))
      : formatDuration(state.metrics.durationMs)
  const busy = isRunning || state.run.status === 'queued'

  return (
    <Collapsible
      data-slot="run-activity-root"
      aria-label="Run activity"
      aria-busy={busy || undefined}
      open={userOpen ?? isRunning}
      onOpenChange={(open) => setUserOpen(open)}
      className="mt-3 mb-0 w-full"
    >
      <CollapsibleTrigger
        data-slot="run-activity-trigger"
        className="group/trigger text-foreground/55 hover:text-foreground/90 data-open:text-foreground/90 flex w-full items-center gap-2.5 rounded-md py-1.5 text-start transition-colors outline-none hover:bg-foreground/[0.03] focus-visible:ring-1 focus-visible:ring-foreground/20"
      >
        <span className="inline-flex size-3 shrink-0 rtl:-scale-x-100">
          <ChevronRightIcon
            data-slot="run-activity-trigger-chevron"
            className="size-3 text-foreground/25 transition-transform duration-200 ease-[cubic-bezier(0.32,0.72,0,1)] group-data-open/trigger:rotate-90 group-data-panel-open/trigger:rotate-90 motion-reduce:transition-none"
          />
        </span>
        <span className="min-w-0 flex-1 truncate text-[13.5px] leading-5">
          Run activity
        </span>
        <span
          className={cn(
            mono,
            'text-foreground/30 shrink-0 leading-5 tabular-nums',
          )}
        >
          {duration}
        </span>
        <StatusChip status={state.run.status} />
      </CollapsibleTrigger>

      <CollapsibleContent
        data-slot="run-activity-content"
        className={cn(collapsePanel, 'data-closed:pointer-events-none outline-none')}
      >
        <div className="mt-1 flex flex-col gap-3 border-t border-foreground/[0.06] pt-2.5 fade-in slide-in-from-top-1 animate-in duration-200">
          <TerminationNotice
            terminationReason={state.run.terminationReason}
            errorCode={state.run.errorCode}
          />

          {state.steps.length > 0 && (
            <div className="flex flex-col">
              {state.steps.map((step) => (
                <div
                  key={step.id}
                  data-depth={stepDepthById.get(step.id) ?? 0}
                  data-parent-id={step.parentId}
                  style={{
                    marginInlineStart: `${Math.min(stepDepthById.get(step.id) ?? 0, 3) * 16}px`,
                  }}
                >
                  <ProcessStepCard
                    step={step}
                    toolNames={step.toolCallIds
                      .map((id) => toolNamesById.get(id))
                      .filter((name): name is string => Boolean(name))}
                    sourceTitles={step.sourceIds
                      .map((id) => sourceTitlesById.get(id))
                      .filter((title): title is string => Boolean(title))}
                    isActive={step.id === state.run.activeStepId}
                  />
                </div>
              ))}
            </div>
          )}

          {state.decisions.length > 0 && (
            <section aria-label="Decisions" className="flex flex-col">
              <h3 className={cn(mono, 'text-foreground/35 font-normal')}>
                Decisions
              </h3>
              <div className="mt-1 flex flex-col">
                {state.decisions.map((decision) => (
                  <DecisionCard key={decision.id} decision={decision} />
                ))}
              </div>
            </section>
          )}

          {state.toolCalls.length > 0 && (
            <section aria-label="Tool calls" className="flex flex-col">
              <h3 className={cn(mono, 'text-foreground/35 font-normal')}>
                Tool calls
              </h3>
              <div className="mt-1 flex flex-col">
                {state.toolCalls.map((tool) => (
                  <ToolExecutionCard key={tool.id} tool={tool} />
                ))}
              </div>
            </section>
          )}

          {state.run.status !== 'running' && state.run.status !== 'queued' && (
            <RunMetricsLine metrics={state.metrics} />
          )}

          {state.caveats && state.caveats.length > 0 && (
            <section aria-label="Caveats" className="flex flex-col gap-1">
              <h3 className={cn(mono, 'text-foreground/35 font-normal')}>
                Caveats
              </h3>
              <ul className="list-disc space-y-0.5 ps-5 text-xs text-foreground/45">
                {state.caveats.map((caveat) => (
                  <li key={caveat}>{caveat}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
