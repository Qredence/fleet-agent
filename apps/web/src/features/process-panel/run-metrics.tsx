import { AlertTriangleIcon, CheckIcon, InfoIcon } from 'lucide-react'

import errorCodes from '@fleet-agent/contracts/error-codes.json'

import { formatDuration } from './status-chip'
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

/**
 * Human labels for public termination reasons. The canonical reason list is
 * packages/contracts/termination-reasons.json; a contract test keeps these
 * keys in sync.
 */
export const TERMINATION_LABELS: Record<string, string> = {
  submit: 'Completed normally',
  // The routed program ends by synthesizing the answer from evidence rather
  // than by calling submit, so this is its normal completion too.
  synthesis: 'Completed normally',
  forced_submit: 'Stopped early — answer may be incomplete',
  max_iters: 'Stopped: iteration limit reached',
  empty_tool_calls: 'Stopped: the agent returned no actions',
  parse_error: 'Stopped: the agent response could not be parsed',
  context_window_exceeded: 'Stopped: conversation is too long for the model',
  timeout: 'Stopped: the agent run timed out',
  cancelled: 'Run cancelled',
  server_restart: 'Stopped: the server restarted during the run',
  approval_required: 'Waiting for approval',
  approval_expired: 'Approval expired',
  approval_invalid: 'Approval could not be applied',
  failed: 'Run failed',
}

/**
 * Presentation copy for public error codes, straight from the shared
 * contract. Clients only ever see these codes.
 */
const ERROR_CODE_LABELS = errorCodes as Record<string, string>

/** Reasons that describe a run that finished as intended, not a problem. */
const NORMAL_TERMINATIONS = new Set(['submit', 'synthesis'])

/**
 * Soft endings: the run produced something usable, or is waiting on the user.
 * Shown as amber caution, never a red alert — unless an errorCode is also set.
 */
const CAUTION_TERMINATIONS = new Set([
  'forced_submit',
  'approval_required',
  'approval_expired',
  'approval_invalid',
])

/** Quiet endings: intentional stop with no failure chrome. */
const QUIET_TERMINATIONS = new Set(['cancelled'])

export type NoticeTone = 'normal' | 'caution' | 'quiet' | 'problem'

export function noticeTone(
  terminationReason: string | undefined,
  errorCode: string | undefined,
): NoticeTone {
  if (errorCode) return 'problem'
  if (!terminationReason) return 'problem'
  if (NORMAL_TERMINATIONS.has(terminationReason)) return 'normal'
  if (CAUTION_TERMINATIONS.has(terminationReason)) return 'caution'
  if (QUIET_TERMINATIONS.has(terminationReason)) return 'quiet'
  return 'problem'
}

function noticeCopy(
  terminationReason: string | undefined,
  errorCode: string | undefined,
): { title: string; detail?: string } {
  const errorLabel = errorCode
    ? (ERROR_CODE_LABELS[errorCode] ?? ERROR_CODE_LABELS.internal_error)
    : undefined
  const reasonLabel = terminationReason
    ? (TERMINATION_LABELS[terminationReason] ?? terminationReason)
    : undefined

  // Prefer the public error message as the headline when we have one; keep the
  // termination reason as quieter context so the trajectory stays readable.
  if (errorLabel) {
    return {
      title: errorLabel,
      detail:
        reasonLabel && reasonLabel !== errorLabel ? reasonLabel : undefined,
    }
  }
  if (reasonLabel) return { title: reasonLabel }
  return { title: 'Run failed' }
}

/** Surfaces how a run ended — prominent for problems, quiet for a clean finish. */
export function TerminationNotice({
  terminationReason,
  errorCode,
}: {
  terminationReason?: string
  errorCode?: string
}) {
  if (!terminationReason && !errorCode) return null

  const tone = noticeTone(terminationReason, errorCode)
  const { title, detail } = noticeCopy(terminationReason, errorCode)
  const isProblem = tone === 'problem'
  const isCaution = tone === 'caution'

  return (
    <div
      role={isProblem ? 'alert' : 'status'}
      className={cn(
        'flex items-start gap-2 rounded-lg px-2.5 py-2 text-xs leading-5',
        isProblem &&
          'border border-red-500/30 bg-red-500/[0.08] text-red-700 dark:text-red-300',
        isCaution &&
          'border border-amber-500/30 bg-amber-500/[0.08] text-amber-700 dark:text-amber-300',
        (tone === 'normal' || tone === 'quiet') && 'text-foreground/45',
      )}
    >
      {isProblem || isCaution ? (
        <AlertTriangleIcon
          aria-hidden="true"
          className="mt-0.5 size-3.5 shrink-0"
        />
      ) : tone === 'normal' ? (
        <CheckIcon
          aria-hidden="true"
          className="mt-0.5 size-3.5 shrink-0 text-emerald-500"
        />
      ) : (
        <InfoIcon
          aria-hidden="true"
          className="mt-0.5 size-3.5 shrink-0 text-foreground/35"
        />
      )}
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {detail && (
          <p
            className={cn(
              'mt-0.5',
              isProblem || isCaution
                ? 'text-current/80'
                : 'text-foreground/40',
            )}
          >
            {detail}
          </p>
        )}
        {errorCode && (
          <p className="mt-1.5">
            <code
              className={cn(
                mono,
                'rounded-md px-1.5 py-0.5',
                isProblem
                  ? 'bg-red-500/15 text-red-800 dark:text-red-200'
                  : 'bg-foreground/[0.06] text-foreground/70',
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
