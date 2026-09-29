/**
 * Frontend environment, validated once at module load.
 *
 * Vite inlines `import.meta.env` at build time, so an operator typo (a URL
 * with a space, a bare host without a scheme) would otherwise surface as a
 * broken request at runtime. Failing loudly here keeps the failure at boot.
 *
 * The dev proxy in `vite.config.ts` reads `VITE_API_PORT` from the shell
 * (`process.env`), because that config runs in Node before `import.meta.env`
 * exists; keep the two defaults aligned when either changes.
 */

import { z } from 'zod'

const DEFAULT_API_BASE_URL = 'http://localhost:8000'

const envSchema = z.object({
  /** Absolute http(s) origin, or a root-relative path for same-origin setups. */
  VITE_API_BASE_URL: z
    .string()
    .refine(
      (value) =>
        value === '' || value.startsWith('/') || /^https?:\/\/\S+$/.test(value),
      {
        message:
          'VITE_API_BASE_URL must be an absolute http(s) URL or a root-relative path',
      },
    )
    .optional(),
  /**
   * Only needed when the API requires FLEET_AGENT_API_KEY. This value ships
   * in the browser bundle and is not user authentication (see SECURITY.md).
   */
  VITE_API_KEY: z.string().optional(),
})

const parsed = envSchema.safeParse(import.meta.env)
if (!parsed.success) {
  const issues = parsed.error.issues
    .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
    .join('; ')
  throw new Error(`Invalid frontend environment — ${issues}`)
}

/**
 * API origin, normalized without a trailing slash because every caller appends
 * a path that already starts with `/`. Operators paste origins with and
 * without the slash — including Amp's own `PUBLIC_URL` — and `//api/projects`
 * is not a path any server or proxy recognizes.
 */
export const API_BASE_URL: string = (
  parsed.data.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/+$/, '')

export const API_KEY: string | undefined = parsed.data.VITE_API_KEY || undefined
