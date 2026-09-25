import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Button } from '@/components/ui/button'

describe('Button', () => {
  it('renders label children when using a render prop template', () => {
    render(<Button render={<a href="/docs" />}>Documentation</Button>)
    const link = screen.getByRole('link', { name: 'Documentation' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/docs')
    expect(link).toHaveTextContent('Documentation')
  })

  it('applies aria-disabled classes when an anchor button is disabled', () => {
    render(
      <Button disabled render={<a href="/disabled-link" />}>
        Disabled Link
      </Button>
    )
    const link = screen.getByRole('link', { name: 'Disabled Link' })
    expect(link).toHaveAttribute('aria-disabled', 'true')
    expect(link.className).toContain('aria-disabled:opacity-50')
  })

  it('renders children and icons in horizontal inline-flex layout wrappers', () => {
    const TestIcon = () => <svg data-testid="test-icon" />
    render(
      <Button leadingIcon={TestIcon}>
        Horizontal Button
      </Button>
    )
    const button = screen.getByRole('button', { name: 'Horizontal Button' })
    expect(button).toBeInTheDocument()
    const icon = screen.getByTestId('test-icon')
    expect(icon).toBeInTheDocument()
    // The content wrapper should use inline-flex for horizontal distribution
    const contentWrapper = icon.parentElement
    expect(contentWrapper?.className).toContain('inline-flex')
    expect(contentWrapper?.className).toContain('items-center')
  })
})
