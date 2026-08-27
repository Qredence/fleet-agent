import {
  Activity,
  Copy,
  ExternalLink,
  FileBox,
  FolderSearch,
  MoreHorizontal,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { useAuiState } from '@assistant-ui/react'
import { useAgUiState } from '@assistant-ui/react-ag-ui'

import { ActivityTab } from '@/components/process-panel/activity-tab'
import { ArtifactsTab } from '@/components/process-panel/artifacts-tab'
import { SourcesTab } from '@/components/process-panel/sources-tab'
import { FileExplorer } from '@/components/process-panel/file-explorer'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { AgentWorkspaceState } from '@/contracts/generated'
import { useHasAgUiRuntime } from '@/features/agent-runtime/ag-ui-presence'
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

type CopyFeedback = 'idle' | 'copied' | 'error'

interface ProcessHeaderProps {
  activeFilePath: string
  onClose: () => void
  compact?: boolean
}

/**
 * Renders a menu item for opening the current file in a new tab.
 *
 * @param canOpen - Whether the current file can be opened
 * @param onOpen - Callback invoked when the file is opened
 */
function ProcessOpenMenuItem({
  canOpen,
  onOpen,
}: {
  canOpen: boolean
  onOpen: () => void
}) {
  return (
    <DropdownMenuItem
      disabled={!canOpen}
      onClick={canOpen ? onOpen : undefined}
      title={canOpen ? undefined : 'Open is available only for README.md.'}
    >
      <ExternalLink className="size-3.5" />
      {canOpen ? 'Open in new tab' : 'Open unavailable for this file'}
    </DropdownMenuItem>
  )
}

/**
 * Displays the process panel title, active file path, and file actions.
 *
 * @param activeFilePath - The currently selected file path.
 * @param compact - Whether to place secondary actions in an overflow menu.
 */
function ProcessHeader({
  activeFilePath,
  onClose,
  compact = false,
}: ProcessHeaderProps) {
  const [copyFeedback, setCopyFeedback] = useState<CopyFeedback>('idle')
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  )
  const canOpen = activeFilePath === 'README.md'

  useEffect(() => {
    return () => {
      if (feedbackTimer.current) clearTimeout(feedbackTimer.current)
    }
  }, [])

  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(activeFilePath)
      setCopyFeedback('copied')
    } catch {
      setCopyFeedback('error')
    }

    if (feedbackTimer.current) clearTimeout(feedbackTimer.current)
    feedbackTimer.current = setTimeout(() => setCopyFeedback('idle'), 1800)
  }

  const copyLabel =
    copyFeedback === 'copied'
      ? 'Copied'
      : copyFeedback === 'error'
        ? 'Copy failed'
        : 'Copy path'
  const feedbackMessage =
    copyFeedback === 'copied'
      ? `${activeFilePath} copied to clipboard.`
      : copyFeedback === 'error'
        ? `Could not copy ${activeFilePath}.`
        : ''

  const openReadme = () => {
    if (canOpen) window.open('/README.md', '_blank')
  }

  return (
    <header className="flex min-h-12 shrink-0 items-center justify-between gap-2 border-b px-3">
      <div className="flex min-w-0 items-center gap-2">
        <h2
          id="process-heading"
          className="shrink-0 text-sm font-semibold text-foreground"
        >
          Process
        </h2>
        <div
          className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground"
          aria-label={`fleet-agent, ${activeFilePath}`}
        >
          <span aria-hidden="true">fleet-agent</span>
          <span aria-hidden="true">&gt;</span>
          <span
            className="min-w-0 truncate font-medium text-foreground"
            title={activeFilePath}
          >
            {activeFilePath}
          </span>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        {!compact && (
          <div className="flex items-center gap-1.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => void handleCopyPath()}
              aria-label={`Copy path ${activeFilePath}`}
            >
              <span>{copyLabel}</span>
              <Copy className="size-3" />
            </Button>

            <Button
              variant="default"
              size="sm"
              className="h-7 gap-1 bg-foreground px-2.5 text-xs text-background disabled:pointer-events-auto disabled:cursor-not-allowed"
              onClick={openReadme}
              disabled={!canOpen}
              aria-label={
                canOpen ? 'Open README.md' : 'Open unavailable for this file'
              }
              title={
                canOpen ? undefined : 'Open is available only for README.md.'
              }
            >
              <span>Open</span>
            </Button>
          </div>
        )}

        {compact && (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <button
                  type="button"
                  className="inline-flex size-7 items-center justify-center rounded-[20px] outline-none transition-colors hover:bg-muted focus-visible:ring-1 focus-visible:ring-[color:var(--focus-ring,#6B97FF)]"
                  aria-label="More process actions"
                />
              }
            >
              <MoreHorizontal className="size-4" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 text-xs">
              <DropdownMenuItem onClick={() => void handleCopyPath()}>
                <Copy className="size-3.5" />
                {copyLabel}
              </DropdownMenuItem>
              <ProcessOpenMenuItem canOpen={canOpen} onOpen={openReadme} />
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label="Close process panel"
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </div>

      <span className="sr-only" role="status" aria-live="polite">
        {feedbackMessage}
      </span>
    </header>
  )
}

/**
 * Displays a centered idle-state message with an accompanying icon.
 *
 * @param icon - The icon to display above the message
 * @param message - The message to display
 */
function IdleState({ icon, message }: { icon: ReactNode; message: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground">
      {icon}
      <p>{message}</p>
    </div>
  )
}

interface ProcessPanelTabsProps {
  agentState?: AgentWorkspaceState
  isRunning?: boolean
  selectedArtifactId: string | null
  activeFilePath: string
  setActiveFilePath: (path: string) => void
}

/**
 * Tabbed body of the process panel. Without an AG-UI agent state (preview
 * routes have no runtime) every tab shows its idle state.
 */
function ProcessPanelTabs({
  agentState,
  isRunning = false,
  selectedArtifactId,
  activeFilePath,
  setActiveFilePath,
}: ProcessPanelTabsProps) {
  const tab = useWorkspaceStore((state) => state.processPanelTab)
  const setTab = useWorkspaceStore((state) => state.setProcessPanelTab)

  return (
    <Tabs
      value={tab}
      onValueChange={(value) => setTab(value as ProcessPanelTab)}
      className="flex min-h-0 flex-1 flex-col"
    >
      <TabsList className="mx-4 mt-2 shrink-0">
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
        <div className="grid grid-cols-1 md:grid-cols-[1fr_200px] h-full min-h-0">
          <div className="min-h-0 overflow-y-auto">
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
          </div>

          <FileExplorer
            selectedPath={activeFilePath}
            onSelectPath={setActiveFilePath}
          />
        </div>
      </TabsContent>
    </Tabs>
  )
}

/**
 * Renders agent-state content when an AG-UI runtime is available, or fallback content otherwise.
 *
 * @param children - Renders the agent workspace state and running status
 * @param fallback - Content to render when no AG-UI runtime is available
 * @returns The runtime-dependent content
 */
function RuntimeAgentStateGate({
  children,
  fallback,
}: {
  children: (
    agentState: AgentWorkspaceState | undefined,
    isRunning: boolean,
  ) => ReactNode
  fallback: ReactNode
}) {
  const hasRuntime = useHasAgUiRuntime()
  if (!hasRuntime) return <>{fallback}</>
  return (
    <RuntimeAgentStateSubscription>{children}</RuntimeAgentStateSubscription>
  )
}

/**
 * Provides the current agent workspace state and running status to child content.
 *
 * @param children - Renders content using the available agent state and running status
 */
function RuntimeAgentStateSubscription({
  children,
}: {
  children: (
    agentState: AgentWorkspaceState | undefined,
    isRunning: boolean,
  ) => ReactNode
}) {
  const agentState = useAgUiState<AgentWorkspaceState>()
  const isRunning = useAuiState((state) => state.thread.isRunning)
  return <>{children(agentState, isRunning)}</>
}

/**
 * Displays activity, sources, and artifacts for the current workspace.
 *
 * Uses idle-state tabs when no agent runtime is available.
 *
 * @param onClose - Closes the process panel.
 * @param compact - Applies compact panel styling and controls when `true`.
 */
export function ProcessPanel({
  onClose,
  compact = false,
}: {
  onClose: () => void
  compact?: boolean
}) {
  const selectedArtifactId = useWorkspaceStore((s) => s.selectedArtifactId)
  const [activeFilePath, setActiveFilePath] = useState('README.md')

  return (
    <aside
      aria-labelledby="process-heading"
      className={`flex h-full min-h-0 flex-col ${surfaceClasses(
        compact ? 3 : 2,
        compact ? 3 : 2,
      )}`}
    >
      <ProcessHeader
        activeFilePath={activeFilePath}
        onClose={onClose}
        compact={compact}
      />

      <RuntimeAgentStateGate
        fallback={
          <ProcessPanelTabs
            selectedArtifactId={selectedArtifactId}
            activeFilePath={activeFilePath}
            setActiveFilePath={setActiveFilePath}
          />
        }
      >
        {(agentState, isRunning) => (
          <ProcessPanelTabs
            agentState={agentState}
            isRunning={isRunning}
            selectedArtifactId={selectedArtifactId}
            activeFilePath={activeFilePath}
            setActiveFilePath={setActiveFilePath}
          />
        )}
      </RuntimeAgentStateGate>
    </aside>
  )
}
