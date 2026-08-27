import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ProcessPanelTab = 'sources' | 'artifacts'
export type ThemeMode = 'dark' | 'light' | 'system'

interface WorkspaceState {
  /** Theme preference: 'dark' | 'light' | 'system'. */
  theme: ThemeMode

  /** Desktop: left panel collapsed to zero width (persisted). */
  sidebarCollapsed: boolean
  /** Desktop: right process panel visible (persisted). */
  processPanelOpen: boolean
  processPanelTab: ProcessPanelTab

  /** Mobile/compact sheet visibility (transient, never persisted). */
  sidebarSheetOpen: boolean
  processSheetOpen: boolean

  /** Artifact selected via an inline thread card (transient). */
  selectedArtifactId: string | null

  setTheme: (theme: ThemeMode) => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setProcessPanelOpen: (open: boolean) => void
  setProcessPanelTab: (tab: ProcessPanelTab) => void
  setSidebarSheetOpen: (open: boolean) => void
  setProcessSheetOpen: (open: boolean) => void
  setSelectedArtifactId: (artifactId: string | null) => void
}

/**
 * Temporarily disables every CSS transition on the page so a theme flip
 * commits instantly instead of smearing across all animated color, border and
 * shadow transitions at once.
 */
function suppressTransitionsDuringThemeFlip() {
  if (typeof document === 'undefined') return

  const style = document.createElement('style')
  style.append(
    document.createTextNode('*,*::before,*::after{transition:none !important}'),
  )
  document.head.append(style)

  // Force a reflow so the new colors commit while transitions are disabled.
  void (document.body ?? document.documentElement).offsetHeight

  // Remove on the next frame so restored transitions cannot catch the flip.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => style.remove())
  })
}

/**
 * Applies the selected theme to the document root.
 *
 * @param theme - The theme mode to apply.
 */
export function applyTheme(theme: ThemeMode) {
  suppressTransitionsDuringThemeFlip()

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
      processPanelTab: 'sources',
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
