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
 * Center conversation pane: assistant-ui Thread over the AG-UI runtime.
 * Shows user messages and final assistant text; `showThinking: false` keeps
 * reasoning out of the transcript (see agent-runtime-provider).
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
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-2 min-w-0">
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground hover:text-foreground"
            aria-label="Toggle sidebar"
            onClick={onSidebarToggle}
          >
            <PanelLeft className="size-4" />
          </Button>
          <h1 className="truncate px-1 text-sm font-medium text-foreground">{title}</h1>
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-foreground"
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
