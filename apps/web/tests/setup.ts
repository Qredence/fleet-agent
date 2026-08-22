import '@testing-library/jest-dom/vitest'

// react-resizable-panels requires ResizeObserver, which jsdom lacks.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver

// jsdom does not implement the Web Animations API used by Base UI internals.
Element.prototype.getAnimations ??= () => []
// jsdom does not implement scrollIntoView.
Element.prototype.scrollIntoView ??= () => {}

/**
 * Controllable matchMedia stub.
 *
 * mockViewport({ mobile: true })      → (max-width: 767px) matches
 * mockViewport({ compact: true })     → (max-width: 1199px) matches
 * mockViewport()                      → wide desktop (no query matches)
 */
export function mockViewport({ mobile = false, compact = false } = {}) {
  window.matchMedia = ((query: string) =>
    ({
      matches: query.includes('767px') ? mobile : query.includes('1199px') ? compact : false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList) as typeof window.matchMedia
}

mockViewport()
