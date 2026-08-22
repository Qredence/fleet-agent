import { Wrench } from 'lucide-react'

import { StatusIcon, formatDuration } from '@/components/process-panel/status-chip'
import type { ToolExecution } from '@/contracts/generated'

/**
 * One tool execution: name, status, duration, and size-limited previews.
 * Long unbroken output must not stretch the panel (break-all + line clamp).
 */
export function ToolExecutionCard({ tool }: { tool: ToolExecution }) {
  return (
    <article
      aria-label={`tool: ${tool.name}`}
      className="flex items-start gap-2 rounded-lg border p-2.5"
    >
      <Wrench className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate text-xs font-medium">
            {tool.name}
          </code>
          <StatusIcon status={tool.status} />
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {formatDuration(tool.durationMs)}
          </span>
        </div>
        {tool.errorMessage && (
          <p className="mt-1 text-xs break-words text-destructive">
            {tool.errorMessage}
          </p>
        )}
        {tool.inputPreview && (
          <p className="mt-1 line-clamp-2 text-xs break-all text-muted-foreground">
            <span className="font-medium">in:</span> {tool.inputPreview}
          </p>
        )}
        {tool.outputPreview && (
          <p className="mt-0.5 line-clamp-2 text-xs break-all text-muted-foreground">
            <span className="font-medium">out:</span> {tool.outputPreview}
          </p>
        )}
      </div>
    </article>
  )
}
