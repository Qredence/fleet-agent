import { useAssistantDataUI } from '@assistant-ui/react'

import { ArtifactCard } from '@/components/elements/artifact-card'
import { useWorkspaceStore } from '@/state/workspace-store'

interface ArtifactData {
  id: string
  name: string
  mediaType: string
  downloadUrl: string
}

function parseArtifactData(value: unknown): ArtifactData | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null
  }
  const data = value as Record<string, unknown>
  const id = typeof data.id === 'string' ? data.id.trim().slice(0, 120) : ''
  const name = typeof data.name === 'string' ? data.name.trim().slice(0, 240) : ''
  const mediaType =
    typeof data.mediaType === 'string' ? data.mediaType.trim().slice(0, 120) : ''
  const downloadUrl =
    typeof data.downloadUrl === 'string' ? data.downloadUrl.trim() : ''
  if (!id || !name || !mediaType || !downloadUrl.startsWith('/api/artifacts/')) {
    return null
  }
  return { id, name, mediaType, downloadUrl }
}

function InlineArtifactCard({ data: rawData }: { data: unknown }) {
  const data = parseArtifactData(rawData)
  const openPanel = useWorkspaceStore((s) => s.setProcessPanelOpen)
  const setTab = useWorkspaceStore((s) => s.setProcessPanelTab)
  const select = useWorkspaceStore((s) => s.setSelectedArtifactId)

  if (!data) return null

  return (
    <button
      type="button"
      aria-label={`Open artifact ${data.name}`}
      onClick={() => {
        openPanel(true)
        setTab('artifacts')
        select(data.id)
      }}
      className="mt-2 block w-full max-w-sm rounded-2xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ArtifactCard
        title={data.name}
        meta={`${data.mediaType} · open in Artifacts`}
        aria-hidden="true"
        className="pointer-events-none w-full max-w-none"
      />
    </button>
  )
}

/**
 * Registers the message-scoped `artifact` data-part renderer on the runtime.
 * Emitted via CUSTOM when a tool finishes an artifact; clicking opens the
 * Artifacts tab and selects the artifact (plan.md Phase 10 inline behavior).
 */
export function ArtifactDataUIRegistration() {
  useAssistantDataUI({
    name: 'artifact',
    render: ({ data }) => <InlineArtifactCard data={data} />,
  })
  return null
}
