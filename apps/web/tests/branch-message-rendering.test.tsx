import { act, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { AssistantRuntimeProvider, useAuiState, useLocalRuntime, type AssistantRuntime } from '@assistant-ui/react'
import { ComposerPreferencesProvider } from '@/components/assistant-ui/composer-elements'
import { Thread } from '@/components/assistant-ui/thread'

// Stateful renderers must be scoped to message identity when branches change.
function StatefulAnswer() {
  const text = useAuiState(s => s.message.content.filter(p => p.type === 'text').map(p => p.text).join(''))
  const [initialText] = useState(text)
  return <p>{initialText}</p>
}
let runtime: AssistantRuntime
function Harness() {
  runtime = useLocalRuntime({ async *run() {} })
  return <AssistantRuntimeProvider runtime={runtime}><ComposerPreferencesProvider><Thread components={{ AssistantMessage: StatefulAnswer }} /></ComposerPreferencesProvider></AssistantRuntimeProvider>
}
describe('branch message rendering', () => {
  it('remounts a stateful answer renderer when the selected message changes', async () => {
    render(<Harness />)
    act(() => runtime.thread.append({ role: 'assistant', content: [{ type: 'text', text: 'Cedar 100' }], parentId: null, startRun: false }))
    await screen.findByText('Cedar 100')
    const first = runtime.thread.getState().messages[0].id
    act(() => runtime.thread.append({ role: 'assistant', content: [{ type: 'text', text: 'Larch 900' }], parentId: null, startRun: false }))
    const branches = runtime.thread.export()
    branches.messages[1].parentId = null
    act(() => runtime.thread.import(branches))
    await screen.findByText('Larch 900')
    act(() => runtime.thread.getMessageByIndex(0).switchToBranch({ branchId: first }))
    await waitFor(() => expect(screen.getByText('Cedar 100')).toBeInTheDocument())
    expect(screen.queryByText('Larch 900')).not.toBeInTheDocument()
  })
})
