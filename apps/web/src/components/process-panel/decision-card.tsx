import { StatusIcon } from '@/components/process-panel/status-chip'
import { cn } from '@/lib/utils'
import type { ProcessDecision } from '@/contracts/generated'

/** A decision with alternatives considered and a user-safe rationale. */
export function DecisionCard({ decision }: { decision: ProcessDecision }) {
  return (
    <article aria-label={`decision: ${decision.title}`} className="w-full">
      <div className="flex items-center gap-2.5 py-1.5 pe-1">
        <StatusIcon status={decision.status} />
        <span className="min-w-0 flex-1 truncate text-[13.5px] text-foreground/70">
          {decision.title}
        </span>
      </div>

      {decision.alternatives.length > 0 && (
        <ul className="space-y-0.5 ps-6 pe-1 text-xs">
          {decision.alternatives.map((alternative) => (
            <li
              key={alternative}
              className={cn(
                'list-disc',
                alternative === decision.selected
                  ? 'text-foreground/80'
                  : 'text-foreground/40',
              )}
            >
              {alternative}
              {alternative === decision.selected && ' · selected'}
            </li>
          ))}
        </ul>
      )}

      {decision.publicRationale && (
        <p className="ps-6 pe-1 text-xs leading-5 text-foreground/40">
          {decision.publicRationale}
        </p>
      )}
    </article>
  )
}
