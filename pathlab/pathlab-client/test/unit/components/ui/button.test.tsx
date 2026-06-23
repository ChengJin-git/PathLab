import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Button } from '@renderer/components/ui/button'

describe('Button', () => {
  it('exposes stable variant and size hooks for premium styling', () => {
    render(<Button variant="primary" size="lg">Launch</Button>)

    const button = screen.getByRole('button', { name: 'Launch' })
    expect(button).toHaveAttribute('data-button-variant', 'primary')
    expect(button).toHaveAttribute('data-button-size', 'lg')
  })

  it('includes reduced-motion-safe interaction classes', () => {
    render(<Button variant="outline">Outline</Button>)

    const button = screen.getByRole('button', { name: 'Outline' })
    expect(button.className).toContain('motion-reduce:transform-none')
    expect(button.className).toContain('motion-reduce:transition-none')
  })
})
