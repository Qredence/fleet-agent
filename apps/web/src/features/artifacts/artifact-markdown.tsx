import { cjk } from '@streamdown/cjk'
import { code } from '@streamdown/code'
import { math } from '@streamdown/math'
import { mermaid } from '@streamdown/mermaid'
import { Streamdown, type StreamdownProps } from 'streamdown'

import { cn } from '@/lib/utils'

const plugins = { code, cjk, math, mermaid } satisfies NonNullable<
  StreamdownProps['plugins']
>

function safeMarkdownUrl(url: string): string | null {
  try {
    const parsed = new URL(url, window.location.origin)
    if (
      (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') ||
      parsed.username ||
      parsed.password
    ) {
      return null
    }
    return parsed.href
  } catch {
    return null
  }
}

const components: NonNullable<StreamdownProps['components']> = {
  img: () => null,
}

export function ArtifactMarkdown({
  content,
  className,
}: {
  content: string
  className?: string
}) {
  return (
    <Streamdown
      className={cn('text-sm', className)}
      components={components}
      controls={false}
      lineNumbers={false}
      linkSafety={{ enabled: false }}
      mermaid={{ config: { securityLevel: 'strict' } }}
      mode="static"
      parseIncompleteMarkdown={false}
      plugins={plugins}
      skipHtml
      urlTransform={safeMarkdownUrl}
    >
      {content}
    </Streamdown>
  )
}
