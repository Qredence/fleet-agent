import { useEffect, useMemo, useRef, useState } from 'react'

import { DecisionCard } from '@/components/process-panel/decision-card'
import { ProcessStepCard } from '@/components/process-panel/process-step-card'
import {
  RunMetricsLine,
  TerminationNotice,
} from '@/components/process-panel/run-metrics'
import { StatusChip, formatDuration } from '@/components/process-panel/status-chip'
import { ToolExecutionCard } from '@/components/process-panel/tool-execution-card'
import type { AgentWorkspaceState } from '@/contracts/generated'

/**
 * Renders the agent run's status, duration, process steps, decisions, tool calls, metrics, termination details, and caveats.
 *
 * @param state - The current agent workspace state
 * @param isRunning - Whether the agent run is active
 */
export function ActivityTab({
  state,
  isRunning,
}: {
  state: AgentWorkspaceState
  isRunning: boolean
}) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const activeStepRef = useRef<HTMLElement | null>(null)

  // Live elapsed clock: ticks once per second while the run is active so the
  // header shows real elapsed time instead of freezing at the last state
  // delta. Pauses (stops ticking) the moment the run settles.
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (!isRunning || !state.run.startedAt) return
    setNowMs(Date.now())
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isRunning, state.run.startedAt])

  // Scroll to the active step only when the user is already near the bottom;
  // never yank the scroll position while they inspect an older step.
  useEffect(() => {
    const scroller = scrollerRef.current
    const active = activeStepRef.current
    if (!scroller || !active) return
    const distanceFromBottom =
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
    if (distanceFromBottom < 120) {
      active.scrollIntoView({ block: 'nearest' })
    }
  }, [state.run.activeStepId, state.run.status, state.run.toolCallCount])

  const toolNamesById = useMemo(
    () => new Map(state.toolCalls.map((tool) => [tool.id, tool.name])),
    [state.toolCalls],
  )
  const sourceTitlesById = useMemo(
    () => new Map(state.sources.map((source) => [source.id, source.title])),
    [state.sources],
  )
  const stepDepthById = useMemo(() => {
    const stepsById = new Map(state.steps.map((step) => [step.id, step]))
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
    state.steps.forEach((step) => depthOf(step.id))
    return depths
  }, [state.steps])

  return (
    <div
      ref={scrollerRef}
      className="h-full space-y-3 overflow-y-auto p-4"
      aria-label="Run activity"
    >
      <div className="flex items-center justify-between gap-2">
        <StatusChip status={state.run.status} />
        <span className="text-xs tabular-nums text-muted-foreground">
          {isRunning && state.run.startedAt
            ? formatDuration(Math.max(0, nowMs - Date.parse(state.run.startedAt)))
            : formatDuration(state.metrics.durationMs)}
        </span>
      </div>

      <TerminationNotice
        terminationReason={state.run.terminationReason}
        errorCode={state.run.errorCode}
      />

      {state.steps.length > 0 && (
        <div className="space-y-1.5">
          {state.steps.map((step) => (
            <div
              key={step.id}
              data-depth={stepDepthById.get(step.id) ?? 0}
              data-parent-id={step.parentId}
              style={{
                marginLeft: `${Math.min(stepDepthById.get(step.id) ?? 0, 3) * 16}px`,
              }}
              ref={(node) => {
                if (step.id === state.run.activeStepId)
                  activeStepRef.current = node
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
        <section aria-label="Decisions" className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground">
            Decisions
          </h3>
          {state.decisions.map((decision) => (
            <DecisionCard key={decision.id} decision={decision} />
          ))}
        </section>
      )}

      {state.toolCalls.length > 0 && (
        <section aria-label="Tool calls" className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground">
            Tool calls
          </h3>
          {state.toolCalls.map((tool) => (
            <ToolExecutionCard key={tool.id} tool={tool} />
          ))}
        </section>
      )}

      {state.run.status !== 'running' && state.run.status !== 'queued' && (
        <RunMetricsLine metrics={state.metrics} />
      )}

      {state.caveats && state.caveats.length > 0 && (
        <section aria-label="Caveats" className="space-y-1">
          <h3 className="text-xs font-semibold text-muted-foreground">Caveats</h3>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {state.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
