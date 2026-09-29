/**
 * Shared localStorage-backed auth state for BYOK provider profiles.
 *
 * Every provider keeps its key, model selection, and custom-model flag under
 * its own storage keys; the read/write/notify mechanics are identical, so
 * they live here once. The provider modules own only their keys, catalogs,
 * and provider-specific flows (OAuth, for OpenRouter).
 */

export interface LocalStorageAuthConfig {
  /** localStorage key for the BYOK API key. */
  storageKey: string
  /** localStorage key for the selected model override. */
  modelStorageKey: string
  /** localStorage key for the custom-model-enabled flag. */
  customModelEnabledKey: string
  /** Model returned while no override is stored. */
  defaultModel: string
}

export interface LocalStorageAuth {
  /** Subscribes to auth and settings changes in this tab and across tabs. */
  onAuthChange(fn: () => void): () => void
  getApiKey(): string | null
  setApiKey(key: string): void
  clearApiKey(): void
  getSelectedModel(): string
  setSelectedModel(model: string): void
  isCustomModelEnabled(): boolean
  setCustomModelEnabled(enabled: boolean): void
}

export function createLocalStorageAuth(
  config: LocalStorageAuthConfig,
): LocalStorageAuth {
  const listeners = new Set<() => void>()

  const notify = () => {
    listeners.forEach((fn) => {
      try {
        fn()
      } catch {
        // Ignore listener errors
      }
    })
  }

  // Cross-tab sync: other tabs update when the key or model changes.
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event) => {
      if (
        event.key === config.storageKey ||
        event.key === config.modelStorageKey ||
        event.key === config.customModelEnabledKey
      ) {
        notify()
      }
    })
  }

  return {
    onAuthChange(fn) {
      listeners.add(fn)
      return () => {
        listeners.delete(fn)
      }
    },
    getApiKey() {
      if (typeof window === 'undefined') return null
      try {
        return localStorage.getItem(config.storageKey)
      } catch {
        return null
      }
    },
    setApiKey(key) {
      if (typeof window === 'undefined') return
      try {
        localStorage.setItem(config.storageKey, key.trim())
        notify()
      } catch {
        // Ignore storage write failures
      }
    },
    clearApiKey() {
      if (typeof window === 'undefined') return
      try {
        localStorage.removeItem(config.storageKey)
        notify()
      } catch {
        // Ignore storage remove failures
      }
    },
    getSelectedModel() {
      if (typeof window === 'undefined') return config.defaultModel
      try {
        return localStorage.getItem(config.modelStorageKey) || config.defaultModel
      } catch {
        return config.defaultModel
      }
    },
    setSelectedModel(model) {
      if (typeof window === 'undefined') return
      try {
        localStorage.setItem(config.modelStorageKey, model.trim())
        notify()
      } catch {
        // Ignore storage write failures
      }
    },
    isCustomModelEnabled() {
      if (typeof window === 'undefined') return false
      try {
        return localStorage.getItem(config.customModelEnabledKey) === 'true'
      } catch {
        return false
      }
    },
    setCustomModelEnabled(enabled) {
      if (typeof window === 'undefined') return
      try {
        localStorage.setItem(
          config.customModelEnabledKey,
          enabled ? 'true' : 'false',
        )
        notify()
      } catch {
        // Ignore storage write failures
      }
    },
  }
}
