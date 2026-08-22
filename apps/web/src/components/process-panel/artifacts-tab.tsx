import { Download, FileBox } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { StatusChip } from '@/components/process-panel/status-chip'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AgentArtifact } from '@/contracts/generated'

function formatSize(sizeBytes: number | undefined): string | undefined {
  if (sizeBytes === undefined) return undefined
  if (sizeBytes < 1024) return `${sizeBytes} B`
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`
}

interface ArtifactsTabProps {
  artifacts: AgentArtifact[]
  selectedArtifactId?: string | null
}

/**
 * Generated artifacts with generation status. Downloads are only offered for
 * ready artifacts with an explicit (controlled) downloadUrl; relative URLs
 * resolve against the API base — never the frontend origin path.
 */
const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

function resolveDownloadUrl(downloadUrl: string | undefined): string | undefined {
  if (!downloadUrl) return undefined
  return downloadUrl.startsWith('/') ? `${API_BASE_URL}${downloadUrl}` : downloadUrl
}

export function ArtifactsTab({ artifacts, selectedArtifactId }: ArtifactsTabProps) {
  const baselineRef = useRef(artifacts.length)
  useEffect(() => {
    baselineRef.current = artifacts.length
  }, [artifacts.length])

  const selectedRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selectedArtifactId])

  if (artifacts.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">No artifacts yet.</p>
    )
  }

  return (
    <div className="h-full space-y-1.5 overflow-y-auto p-4" aria-label="Artifacts">
      {artifacts.map((artifact, index) => {
        const isSelected = artifact.id === selectedArtifactId
        const href = resolveDownloadUrl(artifact.downloadUrl)
        return (
          <article
            key={artifact.id}
            aria-label={`artifact: ${artifact.name}`}
            aria-current={isSelected ? 'true' : undefined}
            ref={(node) => {
              if (isSelected) selectedRef.current = node
            }}
            className={cn(
              'flex items-start gap-2 rounded-lg border p-2.5',
              isSelected && 'border-primary/50 bg-primary/5',
              index >= baselineRef.current && 'motion-safe:animate-highlight-fade',
            )}
          >
            <FileBox className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{artifact.name}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {artifact.mediaType}
                {formatSize(artifact.sizeBytes)
                  ? ` · ${formatSize(artifact.sizeBytes)}`
                  : ''}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <StatusChip status={artifact.status} />
              {artifact.status === 'ready' && href && (
                <Button
                  variant="ghost"
                  size="icon"
                  render={
                    <a
                      href={href}
                      download
                      aria-label={`download artifact: ${artifact.name}`}
                    />
                  }
                >
                  <Download className="size-3.5" />
                </Button>
              )}
            </div>
          </article>
        )
      })}
    </div>
  )
}
