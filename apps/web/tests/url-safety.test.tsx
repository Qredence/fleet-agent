import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { File } from '@/components/assistant-ui/file'
import { Image } from '@/components/assistant-ui/image'
import {
  Card,
  CardButton,
  CardImage,
  CardMedia,
  CardTitle,
} from '@/components/ui/card'
import { SourcesTab } from '@/features/process-panel/sources-tab'
import {
  buildSafeBase64DataUri,
  isSafeArtifactDownloadUrl,
  SAFE_DOWNLOAD_MIME_TYPES,
  SAFE_IMAGE_MIME_TYPES,
  sanitizeDataUri,
  sanitizeHttpUrl,
  sanitizeImageSrc,
  sanitizeNavigationUrl,
} from '@/lib/url-safety'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('url-safety helpers', () => {
  it('allows http(s) URLs and rejects active or credentialed schemes', () => {
    expect(sanitizeHttpUrl('https://dspy.ai/docs')).toBe('https://dspy.ai/docs')
    expect(sanitizeHttpUrl('http://localhost:8000/api')).toBe(
      'http://localhost:8000/api',
    )
    expect(sanitizeHttpUrl('javascript:alert(1)')).toBeNull()
    expect(sanitizeHttpUrl('vbscript:msgbox(1)')).toBeNull()
    expect(sanitizeHttpUrl('data:text/html,<script>alert(1)</script>')).toBeNull()
    expect(sanitizeHttpUrl('file:///etc/passwd')).toBeNull()
    expect(sanitizeHttpUrl('https://user:pass@example.com')).toBeNull()
    expect(sanitizeHttpUrl('https://example.com/\u0000evil')).toBeNull()
  })

  it('validates relative navigation paths safely when allowRelative is set', () => {
    expect(
      sanitizeNavigationUrl('/settings/tools', { allowRelative: true }),
    ).toBe('/settings/tools')
    expect(
      sanitizeNavigationUrl('//evil.com/phish', { allowRelative: true }),
    ).toBeNull()
    expect(
      sanitizeNavigationUrl('/\\evil.com', { allowRelative: true }),
    ).toBeNull()
    expect(
      sanitizeNavigationUrl('javascript:alert(1)', { allowRelative: true }),
    ).toBeNull()
  })

  it('allows raster data URIs and rejects image/svg+xml and text/html', () => {
    expect(
      sanitizeImageSrc('data:image/png;base64,iVBORw0KGgo='),
    ).toBe('data:image/png;base64,iVBORw0KGgo=')
    expect(sanitizeImageSrc('blob:https://app.test/123')).toBe(
      'blob:https://app.test/123',
    )
    expect(sanitizeImageSrc('/assets/logo.png')).toBe('/assets/logo.png')
    expect(
      sanitizeImageSrc('data:image/svg+xml;base64,PHN2Zz4='),
    ).toBeNull()
    expect(
      sanitizeImageSrc('data:image/svg+xml,<svg onload=alert(1)>'),
    ).toBeNull()
    expect(
      sanitizeImageSrc('data:text/html;base64,PHNjcmlwdD4='),
    ).toBeNull()
    expect(sanitizeImageSrc('javascript:alert(1)')).toBeNull()

    expect(
      sanitizeDataUri('data:text/plain;charset=utf-8,hello', SAFE_DOWNLOAD_MIME_TYPES),
    ).toBe('data:text/plain;charset=utf-8,hello')
    expect(
      sanitizeDataUri('data:text/html,<script>1</script>', SAFE_DOWNLOAD_MIME_TYPES),
    ).toBeNull()
    expect(
      sanitizeDataUri('data:image/svg+xml,<svg/>', SAFE_IMAGE_MIME_TYPES),
    ).toBeNull()
  })

  it('enforces safe MIME types on base64 downloads and strict artifact routes', () => {
    expect(buildSafeBase64DataUri('SGVsbG8=', 'text/plain; charset=utf-8')).toBe(
      'data:text/plain;base64,SGVsbG8=',
    )
    expect(buildSafeBase64DataUri('PHNjcmlwdD4=', 'text/html')).toBeNull()
    expect(buildSafeBase64DataUri('PHN2Zz4=', 'image/svg+xml')).toBeNull()
    expect(buildSafeBase64DataUri('javascript:1', 'text/plain')).toBeNull()

    expect(isSafeArtifactDownloadUrl('/api/artifacts/art_123-xyz')).toBe(true)
    expect(isSafeArtifactDownloadUrl('/api/artifacts/a1?download=1')).toBe(false)
    expect(isSafeArtifactDownloadUrl('/api/artifacts/../secret')).toBe(false)
    expect(isSafeArtifactDownloadUrl('https://evil.com/api/artifacts/1')).toBe(
      false,
    )
  })
})

describe('component URL and MIME sanitization', () => {
  it('drops unsafe URIs in SourcesTab and preserves safe http(s) links', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockRejectedValue(new Error('Clipboard blocked'))
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })

    render(
      <SourcesTab
        sources={[
          {
            id: 'unsafe-src',
            title: 'Unsafe Link',
            sourceType: 'web',
            uri: 'javascript:alert(1)',
          },
          {
            id: 'safe-src',
            title: 'Safe Docs',
            sourceType: 'web',
            uri: 'https://dspy.ai/',
          },
        ]}
      />,
    )

    expect(
      screen.queryByRole('link', { name: 'open source: Unsafe Link' }),
    ).not.toBeInTheDocument()
    const safeLink = screen.getByRole('link', { name: 'open source: Safe Docs' })
    expect(safeLink).toHaveAttribute('href', 'https://dspy.ai/')

    // Clipboard failure must be caught silently without unhandled rejections.
    await user.click(
      screen.getByRole('button', { name: 'copy citation: Unsafe Link' }),
    )
    expect(writeText).toHaveBeenCalledWith('Unsafe Link')
  })

  it('blocks SVG and HTML data URIs in Image while allowing raster images', () => {
    const { container: blockedContainer } = render(
      <Image
        type="image"
        image="data:image/svg+xml,<svg onload=alert(1)/>"
        status={{ type: 'complete' }}
      />,
    )
    expect(blockedContainer.querySelector('img')).toBeNull()
    expect(
      blockedContainer.querySelector('[data-slot="image-preview-error"]'),
    ).toBeInTheDocument()

    cleanup()

    const { container: allowedContainer } = render(
      <Image
        type="image"
        image="data:image/png;base64,iVBORw0KGgo="
        filename="chart.png"
        status={{ type: 'complete' }}
      />,
    )
    const img = allowedContainer.querySelector('img')
    expect(img).toHaveAttribute('src', 'data:image/png;base64,iVBORw0KGgo=')
  })

  it('blocks HTML/SVG base64 and data-uri downloads in File while allowing safe files', () => {
    const { container: blockedHtml } = render(
      <File
        type="file"
        data="PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="
        mimeType="text/html"
        filename="payload.html"
        status={{ type: 'complete' }}
      />,
    )
    expect(blockedHtml.querySelector('[data-slot="file-download"]')).toBeNull()

    cleanup()

    const { container: blockedSvgData } = render(
      <File
        type="file"
        data="data:image/svg+xml;base64,PHN2Zz4="
        mimeType="image/svg+xml"
        filename="icon.svg"
        status={{ type: 'complete' }}
      />,
    )
    expect(
      blockedSvgData.querySelector('[data-slot="file-download"]'),
    ).toBeNull()

    cleanup()

    const { container: safeText } = render(
      <File
        type="file"
        data="SGVsbG8="
        mimeType="text/plain"
        filename="notes.txt"
        status={{ type: 'complete' }}
      />,
    )
    const link = safeText.querySelector('[data-slot="file-download"]')
    expect(link).toHaveAttribute('href', 'data:text/plain;base64,SGVsbG8=')
  })

  it('sanitizes Card, CardButton, CardImage, and CardMedia URLs and image sources', () => {
    const { container } = render(
      <div>
        <Card href="javascript:alert(1)">
          <CardImage src="data:image/svg+xml,<svg/>" alt="Unsafe" />
          <CardMedia logo="javascript:alert(2)" />
          <CardTitle>Unsafe Card</CardTitle>
          <CardButton href="javascript:alert(3)">Unsafe Action</CardButton>
        </Card>
        <Card href="/settings/tools">
          <CardImage src="data:image/png;base64,iVBORw0KGgo=" alt="Safe" />
          <CardTitle>Safe Card</CardTitle>
          <CardButton href="https://example.com/docs">Docs</CardButton>
        </Card>
      </div>,
    )

    expect(screen.queryByRole('link', { name: 'Unsafe Card' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Unsafe Action' })).toBeNull()
    expect(container.querySelector('img[alt="Unsafe"]')).toBeNull()

    expect(screen.getByRole('link', { name: 'Safe Card' })).toHaveAttribute(
      'href',
      '/settings/tools',
    )
    expect(screen.getByRole('link', { name: 'Docs' })).toHaveAttribute(
      'href',
      'https://example.com/docs',
    )
    expect(container.querySelector('img[alt="Safe"]')).toHaveAttribute(
      'src',
      'data:image/png;base64,iVBORw0KGgo=',
    )
  })
})
