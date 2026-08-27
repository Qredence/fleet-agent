import { useEffect, useMemo, type ReactNode } from 'react'
import { useDefaultLayout, usePanelRef } from 'react-resizable-panels'

import { ProcessPanel } from '@/components/process-panel/process-panel'
import { ProjectSidebar } from '@/components/projects/project-sidebar'
import { ConversationPane } from '@/components/thread/conversation-pane'
import type { ComposerWorkspaceContext } from '@/components/assistant-ui/composer-elements'
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
import { useProjects } from '@/features/projects/use-projects'
import { useIsCompact, useIsMobile } from '@/hooks/use-media-query'
import { cn } from '@/lib/utils'
import { SurfaceProvider } from '@/lib/surface-context'
import { surfaceClasses } from '@/lib/surface-classes'
import { useWorkspaceStore } from '@/state/workspace-store'

/**
 * Renders the responsive agent workspace for a project conversation.
 *
 * @param projectId - The identifier of the current project.
 * @param threadId - The identifier of the current conversation thread.
 * @param threadTitle - The title of the current conversation.
 * @param customMain - Optional custom content for the main conversation area.
 */
export function AgentWorkspace({
  projectId,
  threadId,
  threadTitle = 'New conversation',
  customMain,
}: {
  projectId?: string
  threadId?: string
  threadTitle?: string
  customMain?: ReactNode
}) {
  const isMobile = useIsMobile()
  const projects = useProjects()
  const projectLabel =
    projects.data?.find((project) => project.id === projectId)?.name ??
    projectId ??
    'Current project'
  const workspaceContext = useMemo<ComposerWorkspaceContext>(
    () => ({
      agentLabel: 'Fleet Agent',
      projectLabel,
      threadLabel: threadTitle,
      ...(projectId ? { projectId } : {}),
      ...(threadId ? { threadId } : {}),
    }),
    [projectId, projectLabel, threadId, threadTitle],
  )

  return isMobile ? (
    <MobileWorkspace
      threadTitle={threadTitle}
      workspaceContext={workspaceContext}
      customMain={customMain}
    />
  ) : (
    <DesktopWorkspace
      threadTitle={threadTitle}
      workspaceContext={workspaceContext}
      customMain={customMain}
    />
  )
}

/**
 * Provides conversation header actions for toggling the sidebar and process panel.
 *
 * @returns Toggle handlers and the process panel's active state.
 */
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

/**
 * Renders the desktop workspace with project navigation, conversation content, and agent process views.
 *
 * @param threadTitle - The title displayed for the current conversation.
 * @param workspaceContext - Context describing the current agent, project, and thread.
 * @param customMain - Optional custom content rendered within the conversation pane.
 */
function DesktopWorkspace({
  threadTitle = 'New conversation',
  workspaceContext,
  customMain,
}: {
  threadTitle?: string
  workspaceContext: ComposerWorkspaceContext
  customMain?: ReactNode
}) {
  const isCompact = useIsCompact()
  const sidebarCollapsed = useWorkspaceStore((s) => s.sidebarCollapsed)
  const setSidebarCollapsed = useWorkspaceStore((s) => s.setSidebarCollapsed)
  const processPanelOpen = useWorkspaceStore((s) => s.processPanelOpen)
  const setProcessPanelOpen = useWorkspaceStore((s) => s.setProcessPanelOpen)
  const processSheetOpen = useWorkspaceStore((s) => s.processSheetOpen)
  const setProcessSheetOpen = useWorkspaceStore((s) => s.setProcessSheetOpen)
  const { toggleSidebar, toggleProcess, processPanelActive } = usePaneActions()

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
    <SurfaceProvider value={1}>
      <div className="flex h-dvh bg-surface-1 text-foreground">
      {isCompact && (
        <Sheet open={processSheetOpen} onOpenChange={setProcessSheetOpen}>
          <SheetContent
            side="right"
            showCloseButton={false}
            className={cn('gap-0 p-0 sm:max-w-md', surfaceClasses(3, 3))}
            aria-label="Process"
          >
            <SheetTitle className="sr-only">Process</SheetTitle>
            <SheetDescription className="sr-only">
              Agent process: steps, tool calls, sources, and artifacts.
            </SheetDescription>
            <ProcessPanel
              compact
              onClose={() => setProcessSheetOpen(false)}
            />
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
          defaultSize={sidebarCollapsed ? '0px' : '260px'}
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
            workspaceContext={workspaceContext}
          >
            {customMain}
          </ConversationPane>
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
    </SurfaceProvider>
  )
}

/**
 * Renders the mobile workspace with conversation content and sheet-based project and process panels.
 *
 * @param threadTitle - The title displayed for the current thread.
 * @param workspaceContext - Context describing the current agent, project, and thread.
 * @param customMain - Optional custom content rendered in the conversation pane.
 */
function MobileWorkspace({
  threadTitle = 'New conversation',
  workspaceContext,
  customMain,
}: {
  threadTitle?: string
  workspaceContext: ComposerWorkspaceContext
  customMain?: ReactNode
}) {
  const sidebarSheetOpen = useWorkspaceStore((s) => s.sidebarSheetOpen)
  const setSidebarSheetOpen = useWorkspaceStore((s) => s.setSidebarSheetOpen)
  const processSheetOpen = useWorkspaceStore((s) => s.processSheetOpen)
  const setProcessSheetOpen = useWorkspaceStore((s) => s.setProcessSheetOpen)
  const { toggleSidebar, toggleProcess, processPanelActive } = usePaneActions()

  return (
    <SurfaceProvider value={1}>
      <div className="flex h-dvh bg-surface-1 text-foreground">
      <Sheet open={sidebarSheetOpen} onOpenChange={setSidebarSheetOpen}>
        <SheetContent
          side="left"
          showCloseButton={false}
          className={cn('gap-0 p-0', surfaceClasses(3, 3))}
          style={{ width: '18rem' }}
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
          className={cn('h-full gap-0 p-0', surfaceClasses(3, 3))}
          aria-label="Process"
        >
          <SheetTitle className="sr-only">Process</SheetTitle>
          <SheetDescription className="sr-only">
            Agent process: steps, tool calls, sources, and artifacts.
          </SheetDescription>
          <ProcessPanel
            compact
            onClose={() => setProcessSheetOpen(false)}
          />
        </SheetContent>
      </Sheet>

      <ConversationPane
        onSidebarToggle={toggleSidebar}
        onProcessToggle={toggleProcess}
        processPanelActive={processPanelActive}
        title={threadTitle}
        workspaceContext={workspaceContext}
      >
        {customMain}
      </ConversationPane>
      </div>
    </SurfaceProvider>
  )
}
