import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Card } from '@renderer/components/ui/card'

describe('Card', () => {
  it('defaults to the work surface tier', () => {
    render(<Card data-testid="card">Core panel</Card>)

    const card = screen.getByTestId('card')
    expect(card).toHaveAttribute('data-surface', 'work')
  })

  it('supports elevated surface styling hooks', () => {
    render(<Card data-testid="card" surface="elevated">Overlay</Card>)

    const card = screen.getByTestId('card')
    expect(card).toHaveAttribute('data-surface', 'elevated')
    expect(card.className).toContain('shadow-[var(--shadow-elevated)]')
  })
})
