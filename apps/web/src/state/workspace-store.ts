import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ProcessPanelTab = 'activity' | 'sources' | 'artifacts'

interface WorkspaceState {
  /** Desktop: left panel collapsed to zero width (persisted). */
  sidebarCollapsed: boolean
  /** Desktop: right process panel visible (persisted). */
  processPanelOpen: boolean
  processPanelTab: ProcessPanelTab

  /** The panel auto-opens on the first tool call exactly once per user. */
  processPanelAutoOpened: boolean

  /** Mobile/compact sheet visibility (transient, never persisted). */
  sidebarSheetOpen: boolean
  processSheetOpen: boolean

  /** Artifact selected via an inline thread card (transient). */
  selectedArtifactId: string | null

  setSidebarCollapsed: (collapsed: boolean) => void
  setProcessPanelOpen: (open: boolean) => void
  setProcessPanelTab: (tab: ProcessPanelTab) => void
  setProcessPanelAutoOpened: (autoOpened: boolean) => void
  setSidebarSheetOpen: (open: boolean) => void
  setProcessSheetOpen: (open: boolean) => void
  setSelectedArtifactId: (artifactId: string | null) => void
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      processPanelOpen: true,
      processPanelTab: 'activity',
      processPanelAutoOpened: false,
      sidebarSheetOpen: false,
      processSheetOpen: false,
      selectedArtifactId: null,

      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      setProcessPanelOpen: (processPanelOpen) => set({ processPanelOpen }),
      setProcessPanelTab: (processPanelTab) => set({ processPanelTab }),
      setProcessPanelAutoOpened: (processPanelAutoOpened) =>
        set({ processPanelAutoOpened }),
      setSidebarSheetOpen: (sidebarSheetOpen) => set({ sidebarSheetOpen }),
      setProcessSheetOpen: (processSheetOpen) => set({ processSheetOpen }),
      setSelectedArtifactId: (selectedArtifactId) => set({ selectedArtifactId }),
    }),
    {
      name: 'fleet-agent-workspace',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        processPanelOpen: state.processPanelOpen,
        processPanelTab: state.processPanelTab,
        processPanelAutoOpened: state.processPanelAutoOpened,
      }),
    },
  ),
)
