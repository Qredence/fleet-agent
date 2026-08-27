import { FileBox, FolderSearch, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { useAgUiState } from '@assistant-ui/react-ag-ui'

import { ArtifactsTab } from '@/components/process-panel/artifacts-tab'
import { SourcesTab } from '@/components/process-panel/sources-tab'
import { FileExplorer } from '@/components/process-panel/file-explorer'
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
  { value: 'sources', label: 'Sources' },
  { value: 'artifacts', label: 'Artifacts' },
]

/**
 * Minimal process header: a plain heading and a close action. The file path
 * lives with the file explorer; no breadcrumb, copy, or open actions.
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
 * Renders the process panel showing sources, artifacts, and file exploration.
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
  const hasAgUi = useHasAgUiRuntime()
  return hasAgUi ? (
    <ActiveProcessPanel onClose={onClose} customContent={customContent} />
  ) : (
    <FallbackProcessPanel onClose={onClose} customContent={customContent} />
  )
}

function ActiveProcessPanel({
  onClose,
  customContent,
}: {
  onClose: () => void
  customContent?: ReactNode
}) {
  const [selectedFilePath, setSelectedFilePath] = useState('README.md')
  const activeTab = useWorkspaceStore((s) => s.processPanelTab)
  const setActiveTab = useWorkspaceStore((s) => s.setProcessPanelTab)

  const state = useAgUiState<AgentWorkspaceState>()

  const sources = state?.sources ?? []
  const artifacts = state?.artifacts ?? []

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
        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as ProcessPanelTab)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="flex shrink-0 items-center justify-between border-b px-4">
            <TabsList className="h-10 gap-4 bg-transparent p-0">
              {TABS.map(({ value, label }) => {
                const count =
                  value === 'sources' ? sources.length : artifacts.length
                return (
                  <TabsTrigger
                    key={value}
                    value={value}
                    className="relative h-10 rounded-none border-b-2 border-transparent px-1 pb-2 pt-2 text-xs font-medium text-muted-foreground shadow-none transition-none data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:shadow-none"
                  >
                    {label}
                    {count > 0 && (
                      <span className="ms-1.5 rounded-full bg-muted px-1.5 py-0.2 text-[10px] font-semibold text-muted-foreground">
                        {count}
                      </span>
                    )}
                  </TabsTrigger>
                )
              })}
            </TabsList>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <TabsContent
              value="sources"
              className="mt-0 h-full p-4 data-[state=inactive]:hidden"
            >
              {sources.length === 0 ? (
                <EmptyTabState
                  icon={FolderSearch}
                  title="No sources discovered"
                  description="Sources referenced during agent runs will appear here."
                />
              ) : (
                <SourcesTab sources={sources} />
              )}
            </TabsContent>

            <TabsContent
              value="artifacts"
              className="mt-0 h-full p-4 data-[state=inactive]:hidden"
            >
              {artifacts.length === 0 ? (
                <EmptyTabState
                  icon={FileBox}
                  title="No artifacts generated"
                  description="Files, reports, and code produced by the agent will be listed here."
                />
              ) : (
                <ArtifactsTab artifacts={artifacts} />
              )}
            </TabsContent>
          </div>

          <FileExplorer
            selectedPath={selectedFilePath}
            onSelectPath={setSelectedFilePath}
          />
        </Tabs>
      )}
    </aside>
  )
}

function FallbackProcessPanel({
  onClose,
  customContent,
}: {
  onClose: () => void
  customContent?: ReactNode
}) {
  const [selectedFilePath, setSelectedFilePath] = useState('README.md')
  const activeTab = useWorkspaceStore((s) => s.processPanelTab)
  const setActiveTab = useWorkspaceStore((s) => s.setProcessPanelTab)

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
        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as ProcessPanelTab)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="flex shrink-0 items-center justify-between border-b px-4">
            <TabsList className="h-10 gap-4 bg-transparent p-0">
              {TABS.map(({ value, label }) => (
                <TabsTrigger
                  key={value}
                  value={value}
                  className="relative h-10 rounded-none border-b-2 border-transparent px-1 pb-2 pt-2 text-xs font-medium text-muted-foreground shadow-none transition-none data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:shadow-none"
                >
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <TabsContent
              value="sources"
              className="mt-0 h-full p-4 data-[state=inactive]:hidden"
            >
              <EmptyTabState
                icon={FolderSearch}
                title="No sources discovered"
                description="Sources referenced during agent runs will appear here."
              />
            </TabsContent>

            <TabsContent
              value="artifacts"
              className="mt-0 h-full p-4 data-[state=inactive]:hidden"
            >
              <EmptyTabState
                icon={FileBox}
                title="No artifacts generated"
                description="Files, reports, and code produced by the agent will be listed here."
              />
            </TabsContent>
          </div>

          <FileExplorer
            selectedPath={selectedFilePath}
            onSelectPath={setSelectedFilePath}
          />
        </Tabs>
      )}
    </aside>
  )
}

function EmptyTabState({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof FolderSearch
  title: string
  description: string
}) {
  return (
    <div className="flex h-48 flex-col items-center justify-center gap-2 text-center">
      <Icon className="size-6 text-muted-foreground" />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
