import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'

describe('Card accessibility and interactive overlay', () => {
  afterEach(() => {
    cleanup()
  })

  it('wires CardTitle to interactive stretched button via aria-labelledby when label is omitted', () => {
    const handleClick = () => {}
    render(
      <Card onClick={handleClick}>
        <CardHeader>
          <CardTitle>Optimizer Settings</CardTitle>
          <CardDescription>Configure optimization hyperparameters</CardDescription>
        </CardHeader>
      </Card>
    )

    const button = screen.getByRole('button', { name: 'Optimizer Settings' })
    expect(button).toBeInTheDocument()

    const titleElement = screen.getByText('Optimizer Settings', { selector: '[data-slot="card-title"] span:not([aria-hidden])' })
    const titleId = titleElement.closest('[data-slot="card-title"]')?.getAttribute('id')
    expect(titleId).toBeTruthy()
    expect(button.getAttribute('aria-labelledby')).toBe(titleId)
  })

  it('uses explicit label prop for accessible name when provided', () => {
    const handleClick = () => {}
    render(
      <Card onClick={handleClick} label="Custom Action Label">
        <CardHeader>
          <CardTitle>Card Title</CardTitle>
        </CardHeader>
      </Card>
    )

    const button = screen.getByRole('button', { name: 'Custom Action Label' })
    expect(button).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-label', 'Custom Action Label')
    expect(button).not.toHaveAttribute('aria-labelledby')
  })

  it('uses explicit aria-label prop when provided', () => {
    const handleClick = () => {}
    render(
      <Card onClick={handleClick} aria-label="Aria Label Action">
        <CardContent>Some content</CardContent>
      </Card>
    )

    const button = screen.getByRole('button', { name: 'Aria Label Action' })
    expect(button).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-label', 'Aria Label Action')
  })

  it('uses explicit aria-labelledby prop when provided', () => {
    const handleClick = () => {}
    render(
      <div>
        <h3 id="external-title">External Heading</h3>
        <Card onClick={handleClick} aria-labelledby="external-title">
          <CardContent>Content</CardContent>
        </Card>
      </div>
    )

    const button = screen.getByRole('button', { name: 'External Heading' })
    expect(button).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-labelledby', 'external-title')
  })

  it('derives accessible name fallback from text content when no CardTitle is present', () => {
    const handleClick = () => {}
    render(
      <Card onClick={handleClick}>
        <CardContent>
          <span>Fallback plain text action</span>
        </CardContent>
      </Card>
    )

    const button = screen.getByRole('button', { name: 'Fallback plain text action' })
    expect(button).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-label', 'Fallback plain text action')
  })

  it('falls back to "Card" when interactive card is empty and has no label', () => {
    const handleClick = () => {}
    render(<Card onClick={handleClick} />)

    const button = screen.getByRole('button', { name: 'Card' })
    expect(button).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-label', 'Card')
  })

  it('wires accessible name to stretched link when href is provided', () => {
    render(
      <Card href="/settings/tools">
        <CardHeader>
          <CardTitle>Tools Overview</CardTitle>
        </CardHeader>
      </Card>
    )

    const link = screen.getByRole('link', { name: 'Tools Overview' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/settings/tools')
  })

  it('does not render overlay when disabled', () => {
    const handleClick = () => {}
    render(
      <Card onClick={handleClick} disabled>
        <CardTitle>Disabled Card</CardTitle>
      </Card>
    )

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('does not render overlay when card is not interactive', () => {
    render(
      <Card>
        <CardTitle>Static Card</CardTitle>
      </Card>
    )

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
