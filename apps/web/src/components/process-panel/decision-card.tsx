import { Scale } from 'lucide-react'

import { StatusChip } from '@/components/process-panel/status-chip'
import { cn } from '@/lib/utils'
import type { ProcessDecision } from '@/contracts/generated'

/** A decision with alternatives considered and a user-safe rationale. */
export function DecisionCard({ decision }: { decision: ProcessDecision }) {
  return (
    <article
      aria-label={`decision: ${decision.title}`}
      className="rounded-lg border p-2.5"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Scale className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate text-sm font-medium">{decision.title}</span>
        </div>
        <StatusChip status={decision.status} />
      </div>

      {decision.alternatives.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-6 text-xs">
          {decision.alternatives.map((alternative) => (
            <li
              key={alternative}
              className={cn(
                'list-disc',
                alternative === decision.selected
                  ? 'font-medium text-foreground'
                  : 'text-muted-foreground',
              )}
            >
              {alternative}
              {alternative === decision.selected && ' · selected'}
            </li>
          ))}
        </ul>
      )}

      {decision.publicRationale && (
        <p className="mt-1.5 pl-6 text-xs text-muted-foreground">
          {decision.publicRationale}
        </p>
      )}
    </article>
  )
}
