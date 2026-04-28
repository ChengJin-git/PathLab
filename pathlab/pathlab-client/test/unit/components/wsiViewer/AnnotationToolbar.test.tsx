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

describe('AnnotationToolbar label selector', () => {
  it('keeps visible labels out of the top bar so the toolbar stays one row', () => {
    render(<AnnotationToolbar {...baseProps} visibleLabels={['A', 'B']} />)

    expect(screen.queryByRole('button', { name: 'A', pressed: true })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'B', pressed: false })).not.toBeInTheDocument()
  })

  it('switches labels from the compact dropdown instead of top-bar chips', () => {
    const onLabelChange = vi.fn()
    render(
      <AnnotationToolbar {...baseProps} visibleLabels={['A', 'B']} onLabelChange={onLabelChange} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'A' }))
    fireEvent.click(screen.getByRole('button', { name: 'B' }))
    expect(onLabelChange).toHaveBeenCalledWith('B')
  })

  it('does not render all labels as top-bar chips when visibleLabels is omitted', () => {
    render(<AnnotationToolbar {...baseProps} />)

    expect(screen.queryByRole('button', { name: 'A', pressed: true })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'B', pressed: false })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'C', pressed: false })).not.toBeInTheDocument()
  })

  it('keeps missing-label management out of the top toolbar', () => {
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

    expect(screen.queryByText('annotation.labelMissingInMode')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'annotation.createLabelInMode' })).not.toBeInTheDocument()
    expect(onCreateCurrentLabelInMode).not.toHaveBeenCalled()
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

  it('renders the current label color on the compact selector', () => {
    render(<AnnotationToolbar {...baseProps} visibleLabels={['A', 'B']} />)

    const selector = screen.getByRole('button', { name: 'A' })

    expect(selector.querySelector('span[style*="background-color: rgb(239, 68, 68)"]')).toBeInTheDocument()
  })
})
