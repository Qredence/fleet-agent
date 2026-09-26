import { ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'

import { StatusIcon, formatDuration } from '@/components/process-panel/status-chip'
import { ToolExecutionCard } from '@/components/process-panel/tool-execution-card'
import { mono } from '@/lib/surfaces'
import { cn } from '@/lib/utils'
import type { ProcessStep, ToolExecution } from '@/contracts/generated'

interface ProcessStepCardProps {
  step: ProcessStep
  tools: ToolExecution[]
  sourceTitles: string[]
  isActive: boolean
  /** When true, nested tools show input/output previews; otherwise name+status. */
  detailedTools?: boolean
}

/**
 * Collapsed: one quiet row — chevron, status, title, duration, live summary.
 * Expanded: nested tool cards and evidence. Steps with no tool or evidence
 * detail stay quiet rows. Active and failed steps with detail open by default
 * so the process panel timeline stays scannable without a hunt.
 * Durations under a tenth of a second are noise and stay hidden.
 */
const DURATION_FLOOR_MS = 100

export function ProcessStepCard({
  step,
  tools,
  sourceTitles,
  isActive,
  detailedTools = true,
}: ProcessStepCardProps) {
  const hasDetails = tools.length > 0 || sourceTitles.length > 0
  const preferOpen =
    hasDetails && (isActive || step.status === 'failed')
  const [expanded, setExpanded] = useState(() => preferOpen)
  const showLiveCursor =
    isActive && step.status === 'running' && step.publicSummary
  const showDuration =
    step.durationMs === undefined || step.durationMs >= DURATION_FLOOR_MS

  const row = (
    <>
      {hasDetails ? (
        <span className="mt-1 inline-flex size-3 shrink-0 rtl:-scale-x-100">
          <ChevronRightIcon
            className={cn(
              'size-3 text-foreground/25 transition-transform duration-200 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none',
              expanded && 'rotate-90',
            )}
          />
        </span>
      ) : (
        <span aria-hidden className="mt-1 size-3 shrink-0" />
      )}
      <StatusIcon status={step.status} />
      <span
        className={cn(
          'min-w-0 flex-1 truncate text-[13.5px] leading-5',
          isActive ? 'text-foreground/90' : 'text-foreground/55',
        )}
      >
        {step.title}
      </span>
      {showDuration && (
        <span
          className={cn(
            mono,
            'text-foreground/25 shrink-0 leading-5 tabular-nums',
          )}
        >
          {formatDuration(step.durationMs)}
        </span>
      )}
    </>
  )

  return (
    <article
      aria-label={`step: ${step.title}`}
      data-active={isActive || undefined}
      data-expanded={expanded || undefined}
      className="group/step w-full"
    >
      {hasDetails ? (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
          className="flex w-full items-start gap-2.5 rounded-lg py-1.5 pe-1 text-start transition-colors outline-none hover:bg-foreground/[0.03] focus-visible:ring-1 focus-visible:ring-foreground/20"
        >
          {row}
        </button>
      ) : (
        <div className="flex w-full items-start gap-2.5 py-1.5 pe-1 text-start">
          {row}
        </div>
      )}

      {step.publicSummary && (
        <p
          className={cn(
            'ps-[52px] pe-1 text-xs leading-5',
            step.status === 'failed'
              ? 'text-red-600/80 dark:text-red-400/80'
              : 'text-foreground/40',
          )}
        >
          {step.publicSummary}
          {showLiveCursor && (
            <span
              aria-hidden
              className="ms-0.5 inline-block h-3 w-[2px] translate-y-0.5 bg-foreground/60 motion-safe:animate-pulse"
            />
          )}
        </p>
      )}

      {hasDetails && expanded && (
        <div className="ms-[52px] mt-1 me-1 flex flex-col gap-1.5 border-t border-foreground/[0.06] pt-1.5 text-xs">
          {tools.length > 0 && (
            <div
              aria-label={`tools for step: ${step.title}`}
              className="flex flex-col gap-1"
            >
              {detailedTools
                ? tools.map((tool) => (
                    <ToolExecutionCard key={tool.id} tool={tool} />
                  ))
                : tools.map((tool) => (
                    <NestedToolSummary key={tool.id} tool={tool} />
                  ))}
            </div>
          )}
          {sourceTitles.length > 0 && (
            <div className="flex items-baseline gap-2">
              <span className={cn(mono, 'text-foreground/35 shrink-0')}>
                Evidence
              </span>
              <div className="min-w-0 flex-1">
                {sourceTitles.map((title) => (
                  <div key={title} className="truncate text-foreground/55">
                    {title}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

function NestedToolSummary({ tool }: { tool: ToolExecution }) {
  return (
    <article
      aria-label={`tool: ${tool.name}`}
      className="flex items-center gap-2.5 py-0.5"
    >
      <StatusIcon status={tool.status} />
      <code className={cn(mono, 'min-w-0 flex-1 truncate text-foreground/60')}>
        {tool.name}
      </code>
      <span className="shrink-0 text-xs capitalize text-foreground/35">
        {tool.status}
      </span>
      <span className={cn(mono, 'shrink-0 text-foreground/25 tabular-nums')}>
        {formatDuration(tool.durationMs)}
      </span>
    </article>
  )
}
