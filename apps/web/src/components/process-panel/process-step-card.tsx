import { ChevronRight } from 'lucide-react'
import { useState } from 'react'

import { StatusIcon, formatDuration } from '@/components/process-panel/status-chip'
import { cn } from '@/lib/utils'
import type { ProcessStep } from '@/contracts/generated'

interface ProcessStepCardProps {
  step: ProcessStep
  toolNames: string[]
  sourceTitles: string[]
  isActive: boolean
}

/**
 * Collapsed: one line with status, title, duration and the public summary.
 * Expanded: summary, tools used and evidence for the step.
 */
export function ProcessStepCard({
  step,
  toolNames,
  sourceTitles,
  isActive,
}: ProcessStepCardProps) {
  const [expanded, setExpanded] = useState(isActive)

  return (
    <article
      aria-label={`step: ${step.title}`}
      className={cn(
        'rounded-lg border p-2.5',
        isActive && 'border-primary/40 bg-primary/5',
      )}
    >
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
        className="flex w-full items-start gap-2 text-left"
      >
        <ChevronRight
          className={cn(
            'mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform',
            expanded && 'rotate-90',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusIcon status={step.status} />
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {step.title}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {formatDuration(step.durationMs)}
            </span>
          </div>
          {step.publicSummary && (
            <p className="mt-0.5 pl-5 text-xs text-muted-foreground">
              {step.publicSummary}
            </p>
          )}
        </div>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 border-t pt-2 pl-5 text-xs">
          <dl className="grid grid-cols-[5rem_1fr] gap-y-1">
            {step.publicSummary && (
              <>
                <dt className="font-medium text-muted-foreground">Summary</dt>
                <dd>{step.publicSummary}</dd>
              </>
            )}
            {toolNames.length > 0 && (
              <>
                <dt className="font-medium text-muted-foreground">Tools</dt>
                <dd>
                  {toolNames.length} call{toolNames.length === 1 ? '' : 's'}:{' '}
                  {toolNames.join(', ')}
                </dd>
              </>
            )}
            {sourceTitles.length > 0 && (
              <>
                <dt className="font-medium text-muted-foreground">Evidence</dt>
                <dd>
                  {sourceTitles.map((title) => (
                    <div key={title} className="truncate">
                      {title}
                    </div>
                  ))}
                </dd>
              </>
            )}
          </dl>
        </div>
      )}
    </article>
  )
}
