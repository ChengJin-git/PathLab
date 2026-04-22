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

  it('applies balanced vertical spacing classes to the wrapper', () => {
    render(<PageHeader title="Task list" description="Review active experiments" />)

    const wrapper = screen.getByRole('heading', { name: 'Task list' }).parentElement?.parentElement
    expect(wrapper!.className).toContain('pt-2')
    expect(wrapper!.className).toContain('pb-4')
    expect(wrapper!.className).toContain('mb-4')
  })

  it('top-aligns the title block with actions on desktop so the title row matches button height', () => {
    render(
      <PageHeader title="Results" description="Some description">
        <button type="button">Export</button>
      </PageHeader>
    )

    const wrapper = screen.getByRole('heading', { name: 'Results' }).parentElement?.parentElement
    expect(wrapper!.className).toContain('md:items-start')
    expect(wrapper!.className).not.toContain('md:items-end')
  })
})
