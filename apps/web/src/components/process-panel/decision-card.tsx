import { StatusIcon } from '@/components/process-panel/status-chip'
import { mono } from '@/lib/surfaces'
import { cn } from '@/lib/utils'
import type { ProcessDecision } from '@/contracts/generated'

/**
 * A decision with optional alternatives and a user-safe rationale.
 * When alternatives (or a selected route) are present, surface as a compact
 * route choice; otherwise show the title as an accepted decision line — which
 * matches what the API currently emits from key_decisions (title only).
 */
export function DecisionCard({ decision }: { decision: ProcessDecision }) {
  const isRoute =
    decision.alternatives.length > 0 || Boolean(decision.selected)

  return (
    <article
      aria-label={
        isRoute ? `route: ${decision.title}` : `decision: ${decision.title}`
      }
      data-route={isRoute || undefined}
      className="w-full"
    >
      <div className="flex items-center gap-2.5 py-1.5 pe-1">
        <StatusIcon status={decision.status} />
        <div className="min-w-0 flex-1">
          {isRoute && (
            <span
              className={cn(mono, 'mb-0.5 block text-[10px] text-foreground/35')}
            >
              Route
            </span>
          )}
          <span className="block truncate text-[13.5px] text-foreground/70">
            {decision.title}
          </span>
        </div>
        {decision.selected && decision.alternatives.length === 0 && (
          <span
            className={cn(
              mono,
              'shrink-0 text-[11px] text-foreground/45',
            )}
          >
            {decision.selected}
          </span>
        )}
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
