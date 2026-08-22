import { PanelLeft, PanelRight } from 'lucide-react'

import { Thread } from '@/components/assistant-ui/thread'
import { Button } from '@/components/ui/button'

interface ConversationPaneProps {
  onSidebarToggle: () => void
  onProcessToggle: () => void
  processPanelActive: boolean
  title?: string
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
}: ConversationPaneProps) {
  return (
    <main
      aria-label="Conversation"
      className="flex h-full min-w-0 flex-1 flex-col bg-background"
    >
      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-3">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle sidebar"
          onClick={onSidebarToggle}
        >
          <PanelLeft className="size-4" />
        </Button>
        <h1 className="flex-1 truncate px-1 text-sm font-medium">{title}</h1>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle process panel"
          aria-pressed={processPanelActive}
          onClick={onProcessToggle}
        >
          <PanelRight className="size-4" />
        </Button>
      </header>

      <div className="min-h-0 flex-1">
        <Thread />
      </div>
    </main>
  )
}
