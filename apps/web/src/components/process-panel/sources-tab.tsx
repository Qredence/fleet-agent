import { Copy, ExternalLink } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AgentSource } from '@/contracts/generated'

function hostname(uri: string | undefined): string | undefined {
  if (!uri) return undefined
  try {
    return new URL(uri).hostname
  } catch {
    return uri
  }
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
  // Highlight items appended after the current render baseline.
  const baselineRef = useRef(sources.length)
  useEffect(() => {
    baselineRef.current = sources.length
  }, [sources.length])

  if (sources.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No sources yet.</p>
  }

  return (
    <div className="h-full space-y-1.5 overflow-y-auto p-4" aria-label="Sources">
      {sources.map((source, index) => {
        const link = hostname(source.uri)
        return (
          <article
            key={source.id}
            aria-label={`source: ${source.title}`}
            className={cn(
              'rounded-lg border p-2.5',
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
                {source.uri && (
                  <Button
                    variant="ghost"
                    size="icon"
                    render={
                      <a
                        href={source.uri}
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
                    void navigator.clipboard.writeText(
                      source.uri ? `[${source.title}](${source.uri})` : source.title,
                    )
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
