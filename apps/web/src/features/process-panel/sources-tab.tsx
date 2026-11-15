import { useWorkspaceStore } from '@/state/workspace-store'
import { Copy, ExternalLink, FolderSearch } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { EmptyTabState } from './empty-tab-state'
import { Button } from '@/components/ui/button'
import { sanitizeHttpUrl } from '@/lib/url-safety'
import { cn } from '@/lib/utils'
import type { AgentSource } from '@/contracts/generated'

function hostname(uri: string | undefined): string | undefined {
  const safeUri = sanitizeHttpUrl(uri)
  if (!safeUri) return undefined
  return new URL(safeUri).hostname
}

/**
 * Sources the agent consulted, with their originating tool. Items added
 * mid-run get a brief highlight; untrusted HTML is never rendered.
 */
export function SourcesTab({
  sources,
  toolNamesById,
}: {
  sources: AgentSource[]
  toolNamesById?: Map<string, string>
}) {
  const selected = useWorkspaceStore((state) => state.selectedSourceId)
  useEffect(() => { if (selected) document.getElementById(`source-${selected}`)?.scrollIntoView?.({ block: 'nearest' }) }, [selected])
  // Highlight items appended after the current render baseline.
  const baselineRef = useRef(sources.length)
  useEffect(() => {
    baselineRef.current = sources.length
  }, [sources.length])

  if (sources.length === 0) {
    return (
      <EmptyTabState
        icon={FolderSearch}
        title="No sources discovered"
        description="Sources referenced during agent runs will appear here."
      />
    )
  }

  return (
    <div className="h-full space-y-1.5 overflow-y-auto p-4" aria-label="Sources">
      {sources.map((source, index) => {
        const safeUri = sanitizeHttpUrl(source.uri)
        const link = hostname(safeUri ?? undefined)
        return (
          <article
            key={source.id}
            id={`source-${source.id}`}
            aria-label={`source: ${source.title}`}
            className={cn(
              'rounded-lg border p-2.5',
              selected === source.id && 'ring-2 ring-ring',
              index >= baselineRef.current &&
                'motion-safe:animate-highlight-fade',
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{source.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {source.sourceType}
                  {link ? ` · ${link}` : ''}
                  {source.toolCallId && toolNamesById?.get(source.toolCallId)
                    ? ` · via ${toolNamesById.get(source.toolCallId)}`
                    : ''}
                </p>
              </div>
              <div className="flex shrink-0 gap-1">
                {safeUri && (
                  <Button
                    variant="ghost"
                    size="icon"
                    nativeButton={false}
                    role="link"
                    render={
                      <a
                        href={safeUri}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`open source: ${source.title}`}
                      />
                    }
                  >
                    <ExternalLink className="size-3.5" />
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`copy citation: ${source.title}`}
                  onClick={() => {
                    navigator.clipboard
                      ?.writeText(
                        safeUri ? `[${source.title}](${safeUri})` : source.title,
                      )
                      .catch(() => {})
                  }}
                >
                  <Copy className="size-3.5" />
                </Button>
              </div>
            </div>
            {source.excerpt && (
              <p className="mt-1 line-clamp-3 text-xs break-words text-muted-foreground">
                {source.excerpt}
              </p>
            )}
          </article>
        )
      })}
    </div>
  )
}
