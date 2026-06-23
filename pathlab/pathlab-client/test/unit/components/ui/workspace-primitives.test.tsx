import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  WorkspaceStatCard,
  SegmentedControl,
  EmptyStatePanel,
  SearchField,
} from '@renderer/components/ui/workspace-primitives'

describe('workspace primitives', () => {
  it('renders a metric card with stable premium hooks', () => {
    render(
      <WorkspaceStatCard
        label="Running"
        value="12"
        accent="pathology"
      />,
    )

    const card = screen.getByTestId('workspace-stat-card')
    expect(card).toHaveAttribute('data-accent', 'pathology')
    expect(card.className).toContain('data-[accent=pathology]:border-secondary-200/80')
  })

  it('renders segmented controls with a selected state hook', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()

    render(
      <SegmentedControl
        value="all"
        onChange={onChange}
        options={[
          { value: 'all', label: 'All' },
          { value: 'running', label: 'Running' },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('data-state', 'active')
    await user.click(screen.getByRole('button', { name: 'Running' }))
    expect(onChange).toHaveBeenCalledWith('running')
  })

  it('renders empty-state panels with a tone hook', () => {
    render(
      <EmptyStatePanel
        title="No tasks"
        description="Start a new experiment"
        tone="neutral"
      />,
    )

    expect(screen.getByTestId('workspace-empty-state')).toHaveAttribute('data-tone', 'neutral')
  })

  it('renders a search field with a premium field container', () => {
    render(
      <SearchField
        value="abc"
        onChange={() => undefined}
        placeholder="Search tasks"
      />,
    )

    expect(screen.getByTestId('workspace-search-field')).toHaveAttribute('data-search-field', 'true')
  })
})
