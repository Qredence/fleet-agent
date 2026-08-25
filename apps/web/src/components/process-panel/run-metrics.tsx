import { AlertTriangle, CheckCircle2 } from 'lucide-react'

import { formatDuration } from '@/components/process-panel/status-chip'
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
    <p aria-label="run metrics" className="text-xs text-muted-foreground">
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
}

/** Surfaces how a run ended — prominently for problems, quietly for submit. */
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
      className={
        isProblem
          ? 'flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-xs text-destructive'
          : 'flex items-start gap-2 rounded-lg border p-2.5 text-xs text-muted-foreground'
      }
    >
      {isProblem ? (
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
      ) : (
        <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success" />
      )}
      <div>
        <p className="font-medium">
          {(terminationReason &&
            (TERMINATION_LABELS[terminationReason] ?? terminationReason)) ??
            'Run failed'}
        </p>
        {errorCode && (
          <p className="mt-0.5">
            <code>{errorCode}</code>
          </p>
        )}
      </div>
    </div>
  )
}
