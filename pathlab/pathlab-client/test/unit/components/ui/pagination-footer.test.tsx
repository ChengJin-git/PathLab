import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PaginationFooter } from '@renderer/components/ui/pagination-footer'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const baseProps = {
  page: 1,
  pageSize: 4,
  total: 20,
  onPageChange: vi.fn(),
  onPageSizeChange: vi.fn(),
}

describe('PaginationFooter', () => {
  it('disables the previous button on the first page', () => {
    render(<PaginationFooter {...baseProps} page={1} />)
    const prev = screen.getByText('settings.permissionCenterModal.previous').closest('button')!
    expect(prev).toBeDisabled()
  })

  it('disables the next button on the last page', () => {
    render(<PaginationFooter {...baseProps} page={5} total={20} pageSize={4} />)
    const next = screen.getByText('settings.permissionCenterModal.next').closest('button')!
    expect(next).toBeDisabled()
  })

  it('enables both buttons when on a middle page', () => {
    render(<PaginationFooter {...baseProps} page={2} />)
    const prev = screen.getByText('settings.permissionCenterModal.previous').closest('button')!
    const next = screen.getByText('settings.permissionCenterModal.next').closest('button')!
    expect(prev).not.toBeDisabled()
    expect(next).not.toBeDisabled()
  })

  it('calls onPageChange(page - 1) when the previous button is clicked', () => {
    const onPageChange = vi.fn()
    render(<PaginationFooter {...baseProps} page={3} onPageChange={onPageChange} />)
    const prev = screen.getByText('settings.permissionCenterModal.previous').closest('button')!
    fireEvent.click(prev)
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('calls onPageChange(page + 1) when the next button is clicked', () => {
    const onPageChange = vi.fn()
    render(<PaginationFooter {...baseProps} page={2} onPageChange={onPageChange} />)
    const next = screen.getByText('settings.permissionCenterModal.next').closest('button')!
    fireEvent.click(next)
    expect(onPageChange).toHaveBeenCalledWith(3)
  })

  it('disables both buttons when the disabled prop is true', () => {
    render(<PaginationFooter {...baseProps} page={2} disabled={true} />)
    const prev = screen.getByText('settings.permissionCenterModal.previous').closest('button')!
    const next = screen.getByText('settings.permissionCenterModal.next').closest('button')!
    expect(prev).toBeDisabled()
    expect(next).toBeDisabled()
  })

  it('calls onPageSizeChange with the numeric value when a new page size is selected', async () => {
    const user = userEvent.setup()
    const onPageSizeChange = vi.fn()
    render(
      <PaginationFooter
        page={1} pageSize={4} total={20}
        pageSizeOptions={['4', '6', '9']}
        onPageChange={vi.fn()}
        onPageSizeChange={onPageSizeChange}
      />
    )

    const selectTrigger = screen.getAllByRole('button')[0]
    await user.click(selectTrigger)

    const option6 = await screen.findByRole('option', { name: '6' })
    await user.click(option6)

    expect(onPageSizeChange).toHaveBeenCalledWith(6)
  })
})
