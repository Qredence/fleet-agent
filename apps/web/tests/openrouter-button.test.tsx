import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OpenRouterButton } from '@/components/auth/openrouter-button'
import * as openrouterAuth from '@/lib/openrouter-auth'

describe('OpenRouterButton', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  it('renders with default label and icon', () => {
    render(<OpenRouterButton />)
    const button = screen.getByRole('button', { name: /sign in with openrouter/i })
    expect(button).toBeInTheDocument()
  })

  it('renders custom children when provided', () => {
    render(<OpenRouterButton>Connect with OpenRouter</OpenRouterButton>)
    expect(
      screen.getByRole('button', { name: /connect with openrouter/i }),
    ).toBeInTheDocument()
  })

  it('renders icon variant with accessible sr-only label', () => {
    render(<OpenRouterButton variant="icon" />)
    const button = screen.getByRole('button', { name: /sign in with openrouter/i })
    expect(button).toHaveClass('aspect-square')
  })

  it('renders loading state correctly', () => {
    render(<OpenRouterButton loading />)
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
  })

  it('calls initiateOAuth when clicked without custom onClick', async () => {
    const user = userEvent.setup()
    const initiateSpy = vi
      .spyOn(openrouterAuth, 'initiateOAuth')
      .mockResolvedValue()

    render(<OpenRouterButton />)
    const button = screen.getByRole('button', { name: /sign in with openrouter/i })
    await user.click(button)

    expect(initiateSpy).toHaveBeenCalledTimes(1)
  })

  it('calls custom onClick when provided', async () => {
    const user = userEvent.setup()
    const handleClick = vi.fn()

    render(<OpenRouterButton onClick={handleClick} />)
    const button = screen.getByRole('button', { name: /sign in with openrouter/i })
    await user.click(button)

    expect(handleClick).toHaveBeenCalledTimes(1)
  })
})
