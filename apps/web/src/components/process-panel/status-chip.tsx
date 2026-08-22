import {
  CheckCircle2,
  Circle,
  CircleSlash,
  Clock,
  Loader2,
  XCircle,
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
  idle: <Circle className="size-3.5 text-muted-foreground" />,
  queued: <Clock className="size-3.5 text-muted-foreground" />,
  pending: <Circle className="size-3.5 text-muted-foreground" />,
  considering: <Clock className="size-3.5 text-muted-foreground" />,
  generating: (
    <Loader2 className="size-3.5 text-muted-foreground motion-safe:animate-spin" />
  ),
  running: (
    <Loader2
      data-running="true"
      className="size-3.5 text-primary motion-safe:animate-spin"
    />
  ),
  completed: <CheckCircle2 className="size-3.5 text-success" />,
  accepted: <CheckCircle2 className="size-3.5 text-success" />,
  ready: <CheckCircle2 className="size-3.5 text-success" />,
  failed: <XCircle className="size-3.5 text-destructive" />,
  rejected: <XCircle className="size-3.5 text-destructive" />,
  cancelled: <CircleSlash className="size-3.5 text-muted-foreground" />,
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

export function StatusIcon({ status }: { status: AnyStatus }) {
  return (
    <span aria-label={`status: ${LABELS[status]}`} className="shrink-0">
      {ICONS[status]}
    </span>
  )
}

export function StatusChip({
  status,
  className,
}: {
  status: AnyStatus
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        (status === 'running' || status === 'generating') &&
          'border-primary/30 text-primary',
        (status === 'failed' || status === 'rejected') &&
          'border-destructive/30 text-destructive',
        (status === 'completed' || status === 'accepted' || status === 'ready') &&
          'border-success/30 text-success',
        className,
      )}
    >
      <StatusIcon status={status} />
      {LABELS[status]}
    </span>
  )
}

export function formatDuration(ms: number | undefined): string {
  if (ms === undefined) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
