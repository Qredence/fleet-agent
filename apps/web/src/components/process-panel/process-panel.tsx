import { Activity, X } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import { useAgUiState } from '@assistant-ui/react-ag-ui'

import { ArtifactsTab } from '@/components/process-panel/artifacts-tab'
import { EmptyTabState } from '@/components/process-panel/empty-tab-state'
import { FileExplorer } from '@/components/process-panel/file-explorer'
import { RunActivityPanel } from '@/components/process-panel/run-activity-inline'
import { SourcesTab } from '@/components/process-panel/sources-tab'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { AgentWorkspaceState } from '@/contracts/generated'
import { useHasAgUiRuntime } from '@/features/agent-runtime/ag-ui-presence'
import { cn } from '@/lib/utils'
import { surfaceClasses } from '@/lib/surface-classes'
import {
  useWorkspaceStore,
  type ProcessPanelTab,
} from '@/state/workspace-store'

const TABS: { value: ProcessPanelTab; label: string }[] = [
  { value: 'activity', label: 'Activity' },
  { value: 'sources', label: 'Sources' },
  { value: 'artifacts', label: 'Artifacts' },
]

/**
 * Minimal process header: a plain heading and a close action. The file path
 * lives with the file explorer; no breadcrumb, copy, or open actions.
 *
 * @param onClose - Callback invoked when closing the process panel.
 */
function ProcessHeader({ onClose }: { onClose: () => void }) {
  return (
    <header className="flex min-h-12 shrink-0 items-center justify-between gap-2 border-b px-4">
      <h2
        id="process-heading"
        className="truncate text-sm font-semibold text-foreground"
      >
        Process
      </h2>
      <Button
        variant="ghost"
        size="icon"
        className="size-7"
        aria-label="Close process panel"
        onClick={onClose}
      >
        <X className="size-4" />
      </Button>
    </header>
  )
}

/**
 * Renders the process panel showing run activity, sources, artifacts, and
 * file exploration.
 *
 * The shell is shared by the live runtime and runtime-less preview routes;
 * only the tab bodies differ, and AG-UI hooks are confined to the `Active*`
 * components below because they throw without a mounted runtime.
 *
 * @param onClose - Callback invoked when closing the process panel.
 * @param customContent - Optional custom content to render instead of the standard tabs.
 */
export function ProcessPanel({
  onClose,
  customContent,
}: {
  onClose: () => void
  customContent?: ReactNode
}) {
  return (
    <aside
      data-slot="process-panel"
      aria-labelledby="process-heading"
      className={cn('flex h-full min-w-0 flex-col border-s', surfaceClasses(1))}
    >
      <ProcessHeader onClose={onClose} />

      {customContent ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {customContent}
        </div>
      ) : (
        <ProcessPanelBody />
      )}
    </aside>
  )
}

/** Tab strip, tab bodies, and the docked file explorer. */
function ProcessPanelBody() {
  const hasAgUi = useHasAgUiRuntime()
  const activeTab = useWorkspaceStore((s) => s.processPanelTab)
  const setActiveTab = useWorkspaceStore((s) => s.setProcessPanelTab)
  const [selectedFilePath, setSelectedFilePath] = useState('README.md')

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as ProcessPanelTab)}
        className="flex min-h-0 flex-1 flex-col gap-0"
      >
        <div className="flex shrink-0 items-center border-b px-4">
          <TabsList
            variant="line"
            className="h-10 w-full justify-start gap-4 rounded-none bg-transparent p-0"
          >
            {TABS.map(({ value, label }) => (
              <TabsTrigger
                key={value}
                value={value}
                className="h-full rounded-none border-none px-1 pb-2 pt-2 text-xs font-medium text-muted-foreground"
              >
                {label}
                <TabCountBadge hasAgUi={hasAgUi} tab={value} />
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <TabsContent value="activity" className="mt-0 h-full">
          {hasAgUi ? (
            <RunActivityPanel />
          ) : (
            <EmptyTabState
              icon={Activity}
              title="No activity yet"
              description="Activity from the latest agent run will appear here."
            />
          )}
        </TabsContent>

        <TabsContent value="sources" className="mt-0 h-full">
          {hasAgUi ? (
            <ActiveSourcesTab />
          ) : (
            <SourcesTab sources={[]} />
          )}
        </TabsContent>

        <TabsContent value="artifacts" className="mt-0 h-full">
          {hasAgUi ? (
            <ActiveArtifactsTab />
          ) : (
            <ArtifactsTab artifacts={[]} />
          )}
        </TabsContent>
      </Tabs>

      <FileExplorer
        selectedPath={selectedFilePath}
        onSelectPath={setSelectedFilePath}
      />
    </div>
  )
}

/**
 * Count pill for a tab trigger. AG-UI state is only readable with a mounted
 * runtime, so the hook lives in a component that renders only when one is.
 *
 * @param hasAgUi - Whether an AG-UI runtime is mounted above the panel.
 * @param tab - The tab the count belongs to.
 */
function TabCountBadge({
  hasAgUi,
  tab,
}: {
  hasAgUi: boolean
  tab: ProcessPanelTab
}) {
  if (!hasAgUi) return null
  return <AgUiTabCount tab={tab} />
}

function AgUiTabCount({ tab }: { tab: ProcessPanelTab }) {
  const state = useAgUiState<AgentWorkspaceState>()
  const count =
    tab === 'sources'
      ? (state?.sources.length ?? 0)
      : tab === 'artifacts'
        ? (state?.artifacts.length ?? 0)
        : 0

  if (count === 0) return null

  return (
    <span className="rounded-full bg-muted px-1.5 py-px text-[10px] font-semibold tabular-nums text-muted-foreground">
      {count}
    </span>
  )
}

/** Sources from the live AG-UI state, enriched with tool attribution. */
function ActiveSourcesTab() {
  const state = useAgUiState<AgentWorkspaceState>()
  const toolNamesById = useMemo(
    () =>
      new Map((state?.toolCalls ?? []).map((tool) => [tool.id, tool.name])),
    [state?.toolCalls],
  )

  return (
    <SourcesTab
      sources={state?.sources ?? []}
      toolNamesById={toolNamesById}
    />
  )
}

/** Artifacts from the live AG-UI state. */
function ActiveArtifactsTab() {
  const state = useAgUiState<AgentWorkspaceState>()
  const selectedArtifactId = useWorkspaceStore((s) => s.selectedArtifactId)

  return (
    <ArtifactsTab
      artifacts={state?.artifacts ?? []}
      selectedArtifactId={selectedArtifactId}
    />
  )
}
