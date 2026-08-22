import { FileBox } from 'lucide-react'

import { useAssistantDataUI } from '@assistant-ui/react'
import { useWorkspaceStore } from '@/state/workspace-store'

interface ArtifactData {
  id: string
  name: string
  mediaType: string
  downloadUrl: string
}

function InlineArtifactCard({ data }: { data: ArtifactData }) {
  const openPanel = useWorkspaceStore((s) => s.setProcessPanelOpen)
  const setTab = useWorkspaceStore((s) => s.setProcessPanelTab)
  const select = useWorkspaceStore((s) => s.setSelectedArtifactId)

  return (
    <button
      type="button"
      onClick={() => {
        openPanel(true)
        setTab('artifacts')
        select(data.id)
      }}
      className="mt-2 flex w-full max-w-sm items-center gap-2 rounded-lg border bg-card p-3 text-left text-sm shadow-sm transition-colors hover:border-primary/40"
    >
      <FileBox className="size-4 shrink-0 text-primary" />
      <span className="min-w-0">
        <span className="block truncate font-medium">{data.name}</span>
        <span className="block text-xs text-muted-foreground">
          {data.mediaType} · open in Artifacts
        </span>
      </span>
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
