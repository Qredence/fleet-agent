import {
  CheckIcon,
  CircleIcon,
  CircleSlashIcon,
  ClockIcon,
  Loader2Icon,
  XIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'

import type {
  ArtifactStatus,
  DecisionStatus,
  RunStatus,
  StepStatus,
  ToolCallStatus,
} from '@/contracts/generated'
import { cn } from '@/lib/utils'

type AnyStatus =
  | RunStatus
  | StepStatus
  | DecisionStatus
  | ToolCallStatus
  | ArtifactStatus

const ICONS: Record<AnyStatus, ReactNode> = {
  idle: <CircleIcon className="size-3 text-foreground/25" />,
  queued: <ClockIcon className="size-3 text-foreground/25" />,
  pending: <CircleIcon className="size-3 text-foreground/25" />,
  considering: <ClockIcon className="size-3 text-foreground/25" />,
  generating: (
    <Loader2Icon className="size-3 text-foreground/35 motion-safe:animate-spin" />
  ),
  running: (
    <Loader2Icon
      data-running="true"
      className="size-3 text-foreground/90 motion-safe:animate-spin"
    />
  ),
  completed: <CheckIcon className="size-3 text-emerald-500" />,
  accepted: <CheckIcon className="size-3 text-emerald-500" />,
  ready: <CheckIcon className="size-3 text-emerald-500" />,
  failed: <XIcon className="size-3 text-red-500" />,
  rejected: <XIcon className="size-3 text-red-500" />,
  cancelled: <CircleSlashIcon className="size-3 text-foreground/25" />,
}

const LABELS: Record<AnyStatus, string> = {
  idle: 'Idle',
  queued: 'Queued',
  pending: 'Pending',
  considering: 'Considering',
  generating: 'Generating',
  running: 'Running',
  completed: 'Completed',
  accepted: 'Accepted',
  ready: 'Ready',
  failed: 'Failed',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
}

/** Status icon inside a fixed optical slot, so rows of any status align. */
export function StatusIcon({
  status,
  decorative = false,
}: {
  status: AnyStatus
  decorative?: boolean
}) {
  return (
    <span
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : `status: ${LABELS[status]}`}
      className="flex size-3.5 shrink-0 items-center justify-center"
    >
      {ICONS[status]}
    </span>
  )
}

/** Flat status word with its icon — no pill, no border. */
export function StatusChip({
  status,
  className,
}: {
  status: AnyStatus
  className?: string
}) {
  const tone =
    status === 'failed' || status === 'rejected'
      ? 'text-red-600 dark:text-red-400'
      : status === 'completed' || status === 'accepted' || status === 'ready'
        ? 'text-emerald-600 dark:text-emerald-400'
        : status === 'running' || status === 'generating'
          ? 'text-foreground/60'
          : 'text-foreground/45'

  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 text-[13px] leading-none',
        tone,
        className,
      )}
    >
      <StatusIcon status={status} decorative />
      {LABELS[status]}
    </span>
  )
}

export function formatDuration(ms: number | undefined): string {
  if (ms === undefined) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
