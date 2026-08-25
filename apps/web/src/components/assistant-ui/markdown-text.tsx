import { StreamdownTextPrimitive } from '@assistant-ui/react-streamdown'
import { cjk } from '@streamdown/cjk'
import { code } from '@streamdown/code'
import { math } from '@streamdown/math'
import { mermaid } from '@streamdown/mermaid'

export function MarkdownText() {
  return (
    <StreamdownTextPrimitive
      className="aui-md"
      defer
      plugins={{ code, cjk, math, mermaid }}
      security={{
        allowedImagePrefixes: [],
        allowedLinkPrefixes: ['*'],
        allowedProtocols: ['http', 'https'],
        allowDataImages: false,
      }}
    />
  )
}
