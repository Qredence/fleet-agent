import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    // Portals get a generated hostname per thread, so an orb must accept any
    // host. Amp sets AMP_ORB=1 inside every orb; everywhere else Vite keeps
    // its default DNS-rebinding protection.
    allowedHosts: process.env.AMP_ORB ? true : undefined,
    // The orb serves the SPA and the API from one portal (see
    // .amp/services.yaml), so the app calls /api on its own origin and the
    // dev server forwards those requests to the local API. Requests that
    // already target an absolute VITE_API_BASE_URL bypass this proxy.
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.VITE_API_PORT || '8000'}`,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    testTimeout: 15000,
  },
})
