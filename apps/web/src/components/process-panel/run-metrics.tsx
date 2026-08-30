import { AlertTriangleIcon, CheckIcon } from 'lucide-react'

import { formatDuration } from '@/components/process-panel/status-chip'
import { mono } from '@/lib/surfaces'
import { cn } from '@/lib/utils'
import type { RunMetrics } from '@/contracts/generated'

/** Token usage and counters for a finished (or in-flight) run. */
export function RunMetricsLine({ metrics }: { metrics: RunMetrics }) {
  const parts = [
    metrics.durationMs != null && formatDuration(metrics.durationMs),
    `${metrics.toolCallCount} tool${metrics.toolCallCount === 1 ? '' : 's'}`,
    metrics.modelCallCount != null &&
      `${metrics.modelCallCount} model call${metrics.modelCallCount === 1 ? '' : 's'}`,
    metrics.totalTokens != null &&
      `${metrics.totalTokens.toLocaleString()} tokens`,
  ].filter(Boolean)

  return (
    <p
      aria-label="run metrics"
      className={cn(mono, 'text-foreground/30 tabular-nums')}
    >
      {parts.join(' · ')}
    </p>
  )
}

const TERMINATION_LABELS: Record<string, string> = {
  submit: 'Completed normally',
  forced_submit: 'Completed via forced submission',
  max_iters: 'Stopped: iteration limit reached',
  empty_tool_calls: 'Stopped: the agent returned no actions',
  parse_error: 'Stopped: the agent response could not be parsed',
  context_window_exceeded: 'Stopped: conversation is too long for the model',
  timeout: 'Stopped: the agent run timed out',
  cancelled: 'Run cancelled',
  approval_required: 'Waiting for approval',
  approval_expired: 'Approval expired',
  approval_invalid: 'Approval could not be applied',
}

/** Surfaces how a run ended — prominent for problems, quiet for submit. */
export function TerminationNotice({
  terminationReason,
  errorCode,
}: {
  terminationReason?: string
  errorCode?: string
}) {
  if (!terminationReason && !errorCode) return null

  const isProblem =
    Boolean(errorCode) ||
    (terminationReason !== undefined && terminationReason !== 'submit')

  return (
    <div
      role={isProblem ? 'alert' : 'status'}
      className={cn(
        'flex items-start gap-2 text-xs',
        isProblem
          ? 'text-red-600 dark:text-red-400'
          : 'text-foreground/45',
      )}
    >
      {isProblem ? (
        <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
      ) : (
        <CheckIcon className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
      )}
      <div className="min-w-0">
        <p className="font-medium">
          {(terminationReason &&
            (TERMINATION_LABELS[terminationReason] ?? terminationReason)) ??
            'Run failed'}
        </p>
        {errorCode && (
          <p className="mt-1">
            <code
              className={cn(
                mono,
                'bg-foreground/[0.06] text-foreground/70 rounded-lg px-1.5 py-0.5',
              )}
            >
              {errorCode}
            </code>
          </p>
        )}
      </div>
    </div>
  )
}
