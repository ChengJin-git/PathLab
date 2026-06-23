import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Input } from '@renderer/components/ui/input'

describe('Input', () => {
  it('exposes a stable premium field hook', () => {
    render(<Input aria-label="Dataset name" />)

    const input = screen.getByRole('textbox', { name: 'Dataset name' })
    expect(input).toHaveAttribute('data-premium-field', 'true')
  })

  it('uses the premium focus ring token', () => {
    render(<Input aria-label="Search" />)

    const input = screen.getByRole('textbox', { name: 'Search' })
    expect(input.className).toContain('focus-visible:ring-primary-500/30')
  })
})
