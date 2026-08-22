import { Activity, FileBox, FolderSearch, X } from 'lucide-react'
import type { ReactNode } from 'react'

import { useAuiState } from '@assistant-ui/react'
import { useAgUiState } from '@assistant-ui/react-ag-ui'

import { ActivityTab } from '@/components/process-panel/activity-tab'
import { ArtifactsTab } from '@/components/process-panel/artifacts-tab'
import { SourcesTab } from '@/components/process-panel/sources-tab'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { AgentWorkspaceState } from '@/contracts/generated'
import {
  useWorkspaceStore,
  type ProcessPanelTab,
} from '@/state/workspace-store'

const TABS: { value: ProcessPanelTab; label: string }[] = [
  { value: 'activity', label: 'Activity' },
  { value: 'sources', label: 'Sources' },
  { value: 'artifacts', label: 'Artifacts' },
]

function IdleState({ icon, message }: { icon: ReactNode; message: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground">
      {icon}
      <p>{message}</p>
    </div>
  )
}

/**
 * Right-side process panel. Renders ONLY the AG-UI agent state
 * (useAgUiState) — an intentional, user-safe trace of steps, tool calls,
 * sources, and artifacts. Never parses messages; never sees chain-of-thought.
 *
 * The auto-open-on-first-tool-call behavior lives in AgentWorkspace (this
 * panel is unmounted while closed).
 */
export function ProcessPanel({ onClose }: { onClose: () => void }) {
  const tab = useWorkspaceStore((state) => state.processPanelTab)
  const setTab = useWorkspaceStore((state) => state.setProcessPanelTab)

  const agentState = useAgUiState<AgentWorkspaceState>()
  const isRunning = useAuiState((state) => state.thread.isRunning)
  const selectedArtifactId = useWorkspaceStore((s) => s.selectedArtifactId)

  return (
    <aside
      aria-label="Process"
      className="flex h-full min-h-0 flex-col bg-background"
    >
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-4">
        <h2 className="text-sm font-semibold">Process</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Close process panel"
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </header>

      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as ProcessPanelTab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="mx-4 mt-3 shrink-0">
          {TABS.map(({ value, label }) => (
            <TabsTrigger key={value} value={value}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="activity" className="min-h-0 flex-1">
          {agentState ? (
            <ActivityTab state={agentState} isRunning={isRunning} />
          ) : (
            <IdleState
              icon={<Activity className="size-5" />}
              message="No active run — send a message to see steps and tool calls here."
            />
          )}
        </TabsContent>
        <TabsContent value="sources" className="min-h-0 flex-1">
          {agentState ? (
            <SourcesTab
              sources={agentState.sources}
              toolNamesById={
                new Map(agentState.toolCalls.map((tool) => [tool.id, tool.name]))
              }
            />
          ) : (
            <IdleState
              icon={<FolderSearch className="size-5" />}
              message="Sources the agent consults will appear here."
            />
          )}
        </TabsContent>
        <TabsContent value="artifacts" className="min-h-0 flex-1">
          {agentState ? (
            <ArtifactsTab
              artifacts={agentState.artifacts}
              selectedArtifactId={selectedArtifactId}
            />
          ) : (
            <IdleState
              icon={<FileBox className="size-5" />}
              message="Generated artifacts will appear here."
            />
          )}
        </TabsContent>
      </Tabs>
    </aside>
  )
}
