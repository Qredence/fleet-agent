import { useEffect, useRef } from 'react'

import { useIsCompact } from '@/hooks/use-media-query'
import { useWorkspaceStore } from '@/state/workspace-store'

/**
 * Auto-open the desktop process panel the first time a run emits a tool call —
 * exactly once per user (persisted). Compact/mobile layouts never force a
 * sheet open.
 */
export function useAutoOpenProcessPanel(toolCallCount: number) {
  const isCompact = useIsCompact()
  const autoOpened = useWorkspaceStore((s) => s.processPanelAutoOpened)
  const setAutoOpened = useWorkspaceStore((s) => s.setProcessPanelAutoOpened)
  const setOpen = useWorkspaceStore((s) => s.setProcessPanelOpen)

  const previousCount = useRef(0)
  useEffect(() => {
    if (previousCount.current === 0 && toolCallCount > 0 && !autoOpened) {
      setAutoOpened(true)
      if (!isCompact) setOpen(true)
    }
    previousCount.current = toolCallCount
  }, [toolCallCount, autoOpened, isCompact, setAutoOpened, setOpen])
}
