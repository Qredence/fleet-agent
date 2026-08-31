import { ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'

import { StatusIcon, formatDuration } from '@/components/process-panel/status-chip'
import { mono } from '@/lib/surfaces'
import { cn } from '@/lib/utils'
import type { ProcessStep } from '@/contracts/generated'

interface ProcessStepCardProps {
  step: ProcessStep
  toolNames: string[]
  sourceTitles: string[]
  isActive: boolean
}

/**
 * Collapsed: one quiet row — chevron, status, title, duration, live summary.
 * Expanded: tools used and evidence, separated by a hairline. Steps with no
 * tool or evidence detail stay quiet rows — no toggle, no empty section.
 * Durations under a tenth of a second are noise and stay hidden.
 */
const DURATION_FLOOR_MS = 100

export function ProcessStepCard({
  step,
  toolNames,
  sourceTitles,
  isActive,
}: ProcessStepCardProps) {
  const hasDetails = toolNames.length > 0 || sourceTitles.length > 0
  const [expanded, setExpanded] = useState(() => isActive && hasDetails)
  const showLiveCursor =
    isActive && step.status === 'running' && step.publicSummary
  const showDuration = step.durationMs === undefined || step.durationMs >= DURATION_FLOOR_MS

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
        <p className="ps-[52px] pe-1 text-xs leading-5 text-foreground/40">
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
          {toolNames.length > 0 && (
            <div className="flex items-baseline gap-2">
              <span className={cn(mono, 'text-foreground/35 shrink-0')}>
                Tools
              </span>
              <span className={cn(mono, 'min-w-0 flex-1 text-foreground/55')}>
                {toolNames.length} call{toolNames.length === 1 ? '' : 's'}:{' '}
                {toolNames.join(', ')}
              </span>
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
