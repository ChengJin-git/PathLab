import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { AnnotationToolbar } from '@renderer/components/wsiViewer/AnnotationToolbar'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const baseProps = {
  annotationMode: true,
  onToggleMode: vi.fn(),
  drawingTool: 'polygon' as const,
  onToolChange: vi.fn(),
  currentLabel: 'A',
  onLabelChange: vi.fn(),
  labelColors: { A: '#ef4444', B: '#22c55e', C: '#3b82f6' },
  allLabels: ['A', 'B', 'C'],
}

describe('AnnotationToolbar label palette', () => {
  it('renders visible labels as selectable chips', () => {
    render(<AnnotationToolbar {...baseProps} visibleLabels={['A', 'B']} />)

    const chipA = screen.getByRole('button', { name: 'A', pressed: true })
    const chipB = screen.getByRole('button', { name: 'B', pressed: false })

    expect(chipA).toBeInTheDocument()
    expect(chipB).toBeInTheDocument()
  })

  it('switches labels when a chip is clicked', () => {
    const onLabelChange = vi.fn()
    render(
      <AnnotationToolbar {...baseProps} visibleLabels={['A', 'B']} onLabelChange={onLabelChange} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'B', pressed: false }))
    expect(onLabelChange).toHaveBeenCalledWith('B')
  })

  it('falls back to allLabels when visibleLabels is not provided', () => {
    render(<AnnotationToolbar {...baseProps} />)

    expect(screen.getByRole('button', { name: 'A', pressed: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'B', pressed: false })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'C', pressed: false })).toBeInTheDocument()
  })

  it('shows a missing-label action when current label is absent in this mode', () => {
    const onCreateCurrentLabelInMode = vi.fn()
    render(
      <AnnotationToolbar
        {...baseProps}
        currentLabel="SharedOnly"
        visibleLabels={['A', 'B']}
        missingCurrentLabel
        onCreateCurrentLabelInMode={onCreateCurrentLabelInMode}
      />,
    )

    expect(screen.getByText('annotation.labelMissingInMode')).toBeInTheDocument()
    const actionButton = screen.getByRole('button', { name: 'annotation.createLabelInMode' })
    expect(actionButton).toBeInTheDocument()

    fireEvent.click(actionButton)
    expect(onCreateCurrentLabelInMode).toHaveBeenCalledTimes(1)
  })

  it('does not show missing-label warning when missingCurrentLabel is false', () => {
    render(
      <AnnotationToolbar
        {...baseProps}
        currentLabel="A"
        visibleLabels={['A', 'B']}
        missingCurrentLabel={false}
      />,
    )

    expect(screen.queryByText('annotation.labelMissingInMode')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'annotation.createLabelInMode' }),
    ).not.toBeInTheDocument()
  })

  it('does not show missing-label warning when prop is omitted', () => {
    render(<AnnotationToolbar {...baseProps} currentLabel="A" visibleLabels={['A', 'B']} />)

    expect(screen.queryByText('annotation.labelMissingInMode')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'annotation.createLabelInMode' }),
    ).not.toBeInTheDocument()
  })

  it('renders chips with label colors', () => {
    render(<AnnotationToolbar {...baseProps} visibleLabels={['A', 'B']} />)

    const chipA = screen.getByRole('button', { name: 'A', pressed: true })
    const chipB = screen.getByRole('button', { name: 'B', pressed: false })

    expect(chipA.querySelector('span[style*="background-color: rgb(239, 68, 68)"]')).toBeInTheDocument()
    expect(chipB.querySelector('span[style*="background-color: rgb(34, 197, 94)"]')).toBeInTheDocument()
  })
})
