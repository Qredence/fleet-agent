import { useEffect } from 'react'
import { useDefaultLayout, usePanelRef } from 'react-resizable-panels'

import { useAgUiState } from '@assistant-ui/react-ag-ui'

import { ProcessPanel } from '@/components/process-panel/process-panel'
import { useAutoOpenProcessPanel } from '@/components/process-panel/use-auto-open-process-panel'
import { ProjectSidebar } from '@/components/projects/project-sidebar'
import { ConversationPane } from '@/components/thread/conversation-pane'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet'
import type { AgentWorkspaceState } from '@/contracts/generated'
import { useIsCompact, useIsMobile } from '@/hooks/use-media-query'
import { useWorkspaceStore } from '@/state/workspace-store'

/**
 * Three-pane workspace shell.
 *
 * ≥1200px: sidebar + conversation + process panel, all resizable.
 * 768–1199px: sidebar + conversation; process panel becomes a Sheet.
 * <768px: conversation only; both side panels become Sheets.
 */
export function AgentWorkspace({
  threadTitle = 'New conversation',
}: {
  projectId?: string
  threadId?: string
  threadTitle?: string
}) {
  const isMobile = useIsMobile()
  return isMobile ? <MobileWorkspace threadTitle={threadTitle} /> : <DesktopWorkspace threadTitle={threadTitle} />
}

/** Shared toggle wiring for the conversation header buttons. */
function usePaneActions() {
  const isCompact = useIsCompact()
  const isMobile = useIsMobile()
  const sidebarCollapsed = useWorkspaceStore((s) => s.sidebarCollapsed)
  const setSidebarCollapsed = useWorkspaceStore((s) => s.setSidebarCollapsed)
  const processPanelOpen = useWorkspaceStore((s) => s.processPanelOpen)
  const setProcessPanelOpen = useWorkspaceStore((s) => s.setProcessPanelOpen)
  const setSidebarSheetOpen = useWorkspaceStore((s) => s.setSidebarSheetOpen)
  const processSheetOpen = useWorkspaceStore((s) => s.processSheetOpen)
  const setProcessSheetOpen = useWorkspaceStore((s) => s.setProcessSheetOpen)

  const toggleSidebar = () => {
    if (isMobile) setSidebarSheetOpen(true)
    else setSidebarCollapsed(!sidebarCollapsed)
  }
  const toggleProcess = () => {
    if (isCompact) setProcessSheetOpen(true)
    else setProcessPanelOpen(!processPanelOpen)
  }

  return {
    toggleSidebar,
    toggleProcess,
    // "Active" drives aria-pressed on the header toggle.
    processPanelActive: isCompact ? processSheetOpen : processPanelOpen,
  }
}

function DesktopWorkspace({ threadTitle = 'New conversation' }: { threadTitle?: string }) {
  const isCompact = useIsCompact()
  const sidebarCollapsed = useWorkspaceStore((s) => s.sidebarCollapsed)
  const setSidebarCollapsed = useWorkspaceStore((s) => s.setSidebarCollapsed)
  const processPanelOpen = useWorkspaceStore((s) => s.processPanelOpen)
  const setProcessPanelOpen = useWorkspaceStore((s) => s.setProcessPanelOpen)
  const processSheetOpen = useWorkspaceStore((s) => s.processSheetOpen)
  const setProcessSheetOpen = useWorkspaceStore((s) => s.setProcessSheetOpen)
  const { toggleSidebar, toggleProcess, processPanelActive } = usePaneActions()

  // Auto-open must live here: ProcessPanel unmounts while closed.
  const agentState = useAgUiState<AgentWorkspaceState>()
  useAutoOpenProcessPanel(agentState?.run.toolCallCount ?? 0)

  const sidebarPanelRef = usePanelRef()
  const processPanelRef = usePanelRef()

  // The store is the source of truth; reconcile the panels imperatively.
  useEffect(() => {
    const panel = sidebarPanelRef.current
    if (!panel) return
    if (sidebarCollapsed && !panel.isCollapsed()) panel.collapse()
    if (!sidebarCollapsed && panel.isCollapsed()) panel.expand()
  }, [sidebarCollapsed, sidebarPanelRef])

  useEffect(() => {
    const panel = processPanelRef.current
    if (!panel) return
    if (!processPanelOpen && !panel.isCollapsed()) panel.collapse()
    if (processPanelOpen && panel.isCollapsed()) panel.expand()
  }, [processPanelOpen, processPanelRef])

  // Pixel layout persisted in localStorage per breakpoint mode. Remounting on
  // mode change applies the mode's saved layout from scratch.
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: isCompact ? 'fleet-workspace-compact' : 'fleet-workspace-wide',
  })

  return (
    <div className="flex h-dvh bg-background text-foreground">
      {isCompact && (
        <Sheet open={processSheetOpen} onOpenChange={setProcessSheetOpen}>
          <SheetContent
            side="right"
            showCloseButton={false}
            className="gap-0 p-0 sm:max-w-md"
            aria-label="Process"
          >
            <SheetTitle className="sr-only">Process</SheetTitle>
            <SheetDescription className="sr-only">
              Agent process: steps, tool calls, sources, and artifacts.
            </SheetDescription>
            <ProcessPanel onClose={() => setProcessSheetOpen(false)} />
          </SheetContent>
        </Sheet>
      )}

      <ResizablePanelGroup
        key={isCompact ? 'compact' : 'wide'}
        orientation="horizontal"
        className="h-full"
        defaultLayout={defaultLayout}
        onLayoutChanged={onLayoutChanged}
      >
        <ResizablePanel
          id="sidebar"
          panelRef={sidebarPanelRef}
          collapsible
          collapsedSize="0px"
          minSize="220px"
          maxSize="320px"
          defaultSize={sidebarCollapsed ? '0px' : '248px'}
          onResize={() => {
            // Keep the store truthful when collapse happens by dragging.
            const panel = sidebarPanelRef.current
            if (panel && panel.isCollapsed() !== sidebarCollapsed) {
              setSidebarCollapsed(panel.isCollapsed())
            }
          }}
          className="min-h-0"
        >
          {!sidebarCollapsed && <ProjectSidebar />}
        </ResizablePanel>
        {!sidebarCollapsed && <ResizableHandle id="sidebar-handle" withHandle />}

        <ResizablePanel id="conversation" minSize="560px" className="min-h-0">
          <ConversationPane
            onSidebarToggle={toggleSidebar}
            onProcessToggle={toggleProcess}
            processPanelActive={processPanelActive}
            title={threadTitle}
          />
        </ResizablePanel>

        {!isCompact && processPanelOpen && (
          <ResizableHandle id="process-handle" withHandle />
        )}
        {!isCompact && (
          <ResizablePanel
            id="process"
            panelRef={processPanelRef}
            collapsible
            collapsedSize="0px"
            minSize="320px"
            maxSize="560px"
            defaultSize={processPanelOpen ? '400px' : '0px'}
            onResize={() => {
              const panel = processPanelRef.current
              if (panel && panel.isCollapsed() === processPanelOpen) {
                setProcessPanelOpen(!panel.isCollapsed())
              }
            }}
            className="min-h-0"
          >
            {processPanelOpen && (
              <ProcessPanel onClose={() => setProcessPanelOpen(false)} />
            )}
          </ResizablePanel>
        )}
      </ResizablePanelGroup>
    </div>
  )
}

function MobileWorkspace({ threadTitle = 'New conversation' }: { threadTitle?: string }) {
  const sidebarSheetOpen = useWorkspaceStore((s) => s.sidebarSheetOpen)
  const setSidebarSheetOpen = useWorkspaceStore((s) => s.setSidebarSheetOpen)
  const processSheetOpen = useWorkspaceStore((s) => s.processSheetOpen)
  const setProcessSheetOpen = useWorkspaceStore((s) => s.setProcessSheetOpen)
  const { toggleSidebar, toggleProcess, processPanelActive } = usePaneActions()

  return (
    <div className="flex h-dvh bg-background text-foreground">
      <Sheet open={sidebarSheetOpen} onOpenChange={setSidebarSheetOpen}>
        <SheetContent
          side="left"
          showCloseButton={false}
          className="gap-0 p-0"
          aria-label="Projects and threads"
        >
          <SheetTitle className="sr-only">Projects and threads</SheetTitle>
          <SheetDescription className="sr-only">
            Projects, threads, and account menu.
          </SheetDescription>
          <ProjectSidebar />
        </SheetContent>
      </Sheet>

      <Sheet open={processSheetOpen} onOpenChange={setProcessSheetOpen}>
        <SheetContent
          side="right"
          showCloseButton={false}
          className="h-full gap-0 p-0"
          aria-label="Process"
        >
          <SheetTitle className="sr-only">Process</SheetTitle>
          <SheetDescription className="sr-only">
            Agent process: steps, tool calls, sources, and artifacts.
          </SheetDescription>
          <ProcessPanel onClose={() => setProcessSheetOpen(false)} />
        </SheetContent>
      </Sheet>

      <ConversationPane
        onSidebarToggle={toggleSidebar}
        onProcessToggle={toggleProcess}
        processPanelActive={processPanelActive}
        title={threadTitle}
      />
    </div>
  )
}
