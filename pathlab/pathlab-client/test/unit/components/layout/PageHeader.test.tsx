import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PageHeader } from '@renderer/components/PageHeader'

describe('PageHeader', () => {
  it('renders a stable page-header hook and premium title tracking', () => {
    render(<PageHeader title="Task list" description="Review active experiments" />)

    const heading = screen.getByRole('heading', { name: 'Task list' })
    expect(heading.parentElement?.parentElement).toHaveAttribute('data-page-header', 'true')
    expect(heading.className).toContain('tracking-[-0.035em]')
  })

  it('renders a dedicated actions container when actions are present', () => {
    render(
      <PageHeader title="Results">
        <button type="button">Export</button>
      </PageHeader>
    )

    const actions = screen.getByRole('button', { name: 'Export' }).parentElement
    expect(actions).toHaveAttribute('data-page-header-actions', 'true')
  })
})
