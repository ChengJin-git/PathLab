import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ModalShell } from '@renderer/components/ui/modal-shell'

describe('ModalShell', () => {
  it('renders nothing when isOpen=false', () => {
    render(<ModalShell isOpen={false}><span>hidden</span></ModalShell>)
    expect(screen.queryByText('hidden')).not.toBeInTheDocument()
  })

  it('renders children inside a dialog element when isOpen=true', () => {
    render(<ModalShell isOpen={true}><span>visible</span></ModalShell>)
    expect(screen.getByText('visible')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('calls onClose when the backdrop is clicked', () => {
    const onClose = vi.fn()
    const { container } = render(
      <ModalShell isOpen={true} onClose={onClose}><span>content</span></ModalShell>
    )
    fireEvent.click(container.firstChild as HTMLElement)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not call onClose when dialog content is clicked', () => {
    const onClose = vi.fn()
    render(
      <ModalShell isOpen={true} onClose={onClose}><button type="button">inner</button></ModalShell>
    )
    fireEvent.click(screen.getByText('inner'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose when Escape key is pressed', () => {
    const onClose = vi.fn()
    render(<ModalShell isOpen={true} onClose={onClose}><span>content</span></ModalShell>)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not call onClose for non-Escape key presses', () => {
    const onClose = vi.fn()
    render(<ModalShell isOpen={true} onClose={onClose}><span>content</span></ModalShell>)
    fireEvent.keyDown(document, { key: 'Enter' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('does not error when Escape is pressed without an onClose handler', () => {
    render(<ModalShell isOpen={true}><span>content</span></ModalShell>)
    expect(() => fireEvent.keyDown(document, { key: 'Escape' })).not.toThrow()
  })

  it('applies the correct maxWidth class to the dialog container', () => {
    render(<ModalShell isOpen={true} maxWidth="lg"><span>x</span></ModalShell>)
    expect(screen.getByRole('dialog').className).toContain('max-w-lg')
  })

  it('merges additional className onto the dialog container', () => {
    render(<ModalShell isOpen={true} className="p-6 custom"><span>x</span></ModalShell>)
    expect(screen.getByRole('dialog').className).toContain('custom')
  })

  it('defaults to max-w-md when no maxWidth is specified', () => {
    render(<ModalShell isOpen={true}><span>x</span></ModalShell>)
    expect(screen.getByRole('dialog').className).toContain('max-w-md')
  })
})
