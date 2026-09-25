import { useState } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { ReasoningEffort } from '@/components/assistant-ui/reasoning-effort'

afterEach(() => {
  cleanup()
})

function StatefulReasoningEffort() {
  const [selectedKey, setSelectedKey] = useState('medium')

  return (
    <ReasoningEffort
      levels={[
        { key: 'low', label: 'Low' },
        { key: 'medium', label: 'Medium' },
        { key: 'high', label: 'High' },
      ]}
      selectedKey={selectedKey}
      onSelect={setSelectedKey}
    />
  )
}

describe('ReasoningEffort keyboard navigation', () => {
  it('moves focus and selection with wrapping arrow keys', async () => {
    const user = userEvent.setup()
    render(<StatefulReasoningEffort />)

    await user.tab()
    const medium = screen.getByRole('radio', { name: 'Medium' })
    expect(medium).toHaveFocus()

    await user.keyboard('{ArrowRight}')
    const high = screen.getByRole('radio', { name: 'High' })
    expect(high).toHaveFocus()
    expect(high).toHaveAttribute('aria-checked', 'true')

    await user.keyboard('{ArrowDown}')
    const low = screen.getByRole('radio', { name: 'Low' })
    expect(low).toHaveFocus()
    expect(low).toHaveAttribute('aria-checked', 'true')

    await user.keyboard('{ArrowLeft}')
    expect(high).toHaveFocus()
    expect(high).toHaveAttribute('aria-checked', 'true')
  })
})
