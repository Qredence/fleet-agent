import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ProcessPanelTab = 'activity' | 'sources' | 'artifacts'
export type ThemeMode = 'dark' | 'light' | 'system'

interface WorkspaceState {
  /** Theme preference: 'dark' | 'light' | 'system'. */
  theme: ThemeMode

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

  setTheme: (theme: ThemeMode) => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setProcessPanelOpen: (open: boolean) => void
  setProcessPanelTab: (tab: ProcessPanelTab) => void
  setProcessPanelAutoOpened: (autoOpened: boolean) => void
  setSidebarSheetOpen: (open: boolean) => void
  setProcessSheetOpen: (open: boolean) => void
  setSelectedArtifactId: (artifactId: string | null) => void
}

export function applyTheme(theme: ThemeMode) {
  const root = document.documentElement
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  const isDark = theme === 'dark' || (theme === 'system' && systemDark)

  if (isDark) {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      theme: 'dark',
      sidebarCollapsed: false,
      processPanelOpen: true,
      processPanelTab: 'activity',
      processPanelAutoOpened: false,
      sidebarSheetOpen: false,
      processSheetOpen: false,
      selectedArtifactId: null,

      setTheme: (theme) => {
        applyTheme(theme)
        set({ theme })
      },
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
        theme: state.theme,
        sidebarCollapsed: state.sidebarCollapsed,
        processPanelOpen: state.processPanelOpen,
        processPanelTab: state.processPanelTab,
        processPanelAutoOpened: state.processPanelAutoOpened,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.theme) {
          applyTheme(state.theme)
        } else {
          applyTheme('dark')
        }
      },
    },
  ),
)
