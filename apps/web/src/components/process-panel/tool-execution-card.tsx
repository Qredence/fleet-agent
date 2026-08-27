import { TerminalBlock } from '@/components/elements/terminal-block'
import { StatusIcon, formatDuration } from '@/components/process-panel/status-chip'
import { mono } from '@/lib/surfaces'
import { cn } from '@/lib/utils'
import type { ToolExecution } from '@/contracts/generated'

/**
 * One tool execution: mono name, status, duration, and size-limited previews.
 * Long unbroken output must not stretch the panel (break-all + line clamp).
 */
export function ToolExecutionCard({ tool }: { tool: ToolExecution }) {
  return (
    <article
      aria-label={`tool: ${tool.name}`}
      className="flex items-start gap-2.5 py-0.5"
    >
      <StatusIcon status={tool.status} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <code
            className={cn(
              mono,
              'text-foreground/55 min-w-0 flex-1 truncate',
            )}
          >
            {tool.name}
          </code>
          <span
            className={cn(
              mono,
              'text-foreground/25 shrink-0 tabular-nums',
            )}
          >
            {formatDuration(tool.durationMs)}
          </span>
        </div>
        {tool.errorMessage && (
          <TerminalBlock
            title="error"
            copyText={tool.errorMessage}
            className="mt-1"
          >
            <span className="text-red-600 dark:text-red-400">
              {tool.errorMessage}
            </span>
          </TerminalBlock>
        )}
        {tool.inputPreview && (
          <TerminalBlock
            title="in"
            copyText={tool.inputPreview}
            className="mt-1"
          >
            {tool.inputPreview}
          </TerminalBlock>
        )}
        {tool.outputPreview && (
          <TerminalBlock
            title="out"
            copyText={tool.outputPreview}
            className="mt-1"
          >
            {tool.outputPreview}
          </TerminalBlock>
        )}
      </div>
    </article>
  )
}
