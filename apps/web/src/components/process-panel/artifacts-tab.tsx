import { Download, FileBox } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { ArtifactMarkdown } from '@/features/artifacts/artifact-markdown'
import { StatusChip } from '@/components/process-panel/status-chip'
import { Button } from '@/components/ui/button'
import { apiFetchText } from '@/lib/api-client'
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

const MAX_PREVIEW_CHARS = 64 * 1024

type ArtifactPreviewState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; content: string; truncated: boolean }
  | { status: 'error' }

function useArtifactPreview(artifact: AgentArtifact | undefined): ArtifactPreviewState {
  const [state, setState] = useState<ArtifactPreviewState>({ status: 'idle' })

  useEffect(() => {
    if (
      !artifact ||
      artifact.status !== 'ready' ||
      artifact.mediaType !== 'text/markdown' ||
      !artifact.downloadUrl?.startsWith('/api/artifacts/')
    ) {
      setState({ status: 'idle' })
      return
    }

    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })

    apiFetchText(artifact.downloadUrl, { signal: controller.signal })
      .then((content) => {
        if (!active) return
        setState({
          status: 'ready',
          content: content.slice(0, MAX_PREVIEW_CHARS),
          truncated: content.length > MAX_PREVIEW_CHARS,
        })
      })
      .catch(() => {
        if (active && !controller.signal.aborted) setState({ status: 'error' })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [artifact?.downloadUrl, artifact?.id, artifact?.mediaType, artifact?.status])

  return state
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

  const selectedArtifact = artifacts.find(
    (artifact) => artifact.id === selectedArtifactId,
  )
  const preview = useArtifactPreview(selectedArtifact)

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
              'grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 rounded-lg border p-2.5',
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
                  nativeButton={false}
                  role="link"
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
            {isSelected && preview.status === 'loading' && (
              <p
                className="text-muted-foreground col-span-full border-t pt-3 text-xs"
                role="status"
              >
                Loading Markdown preview…
              </p>
            )}
            {isSelected && preview.status === 'error' && (
              <p
                className="text-muted-foreground col-span-full border-t pt-3 text-xs"
                role="alert"
              >
                The Markdown preview could not be loaded. Use the download button
                to open the artifact.
              </p>
            )}
            {isSelected && preview.status === 'ready' && (
              <div
                className="col-span-full mt-1 max-h-[min(60vh,36rem)] overflow-y-auto border-t pt-3"
                aria-label={`Preview of ${artifact.name}`}
              >
                <ArtifactMarkdown content={preview.content} />
                {preview.truncated && (
                  <p className="text-muted-foreground mt-3 text-xs">
                    Preview truncated. Download the artifact to read the full file.
                  </p>
                )}
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
