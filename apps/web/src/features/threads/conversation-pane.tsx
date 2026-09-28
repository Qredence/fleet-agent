import { PanelLeft, PanelRight } from 'lucide-react'
import type { ReactNode } from 'react'

import type { ComposerWorkspaceContext } from '@/components/assistant-ui/composer-elements'
import { Thread } from '@/components/assistant-ui/thread'
import { Button } from '@/components/ui/button'

interface ConversationPaneProps {
  onSidebarToggle: () => void
  onProcessToggle: () => void
  processPanelActive: boolean
  title?: string
  workspaceContext?: ComposerWorkspaceContext
  children?: ReactNode
}

/**
 * Renders the central conversation area with sidebar and process-panel controls.
 *
 * Custom content is rendered when provided; otherwise, the default conversation thread uses the workspace context.
 *
 * @param workspaceContext - Context supplied to the default conversation thread.
 * @param children - Optional content rendered instead of the default conversation thread.
 */
export function ConversationPane({
  onSidebarToggle,
  onProcessToggle,
  processPanelActive,
  title = 'New conversation',
  workspaceContext,
  children,
}: ConversationPaneProps) {
  return (
    <main
      aria-label="Conversation"
      className="flex h-full min-w-0 flex-1 flex-col bg-surface-1"
    >
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border/50 bg-surface-1/80 backdrop-blur-xs px-3.5">
        <div className="flex items-center gap-2.5 min-w-0">
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground hover:bg-surface-2 hover:text-foreground rounded-lg transition-colors"
            aria-label="Toggle sidebar"
            onClick={onSidebarToggle}
          >
            <PanelLeft className="size-4" />
          </Button>
          <div className="flex items-center gap-2 min-w-0">
            <span className="size-2 shrink-0 rounded-full bg-emerald-500/80 shadow-xs" title="Ready" />
            <h1 className="truncate text-sm font-medium tracking-tight text-foreground">{title}</h1>
          </div>
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:bg-surface-2 hover:text-foreground rounded-lg transition-colors"
          aria-label="Toggle process panel"
          aria-pressed={processPanelActive}
          onClick={onProcessToggle}
        >
          <PanelRight className="size-4" />
        </Button>
      </header>

      <div className="min-h-0 flex-1">
        {children ?? <Thread workspaceContext={workspaceContext} />}
      </div>
    </main>
  )
}
