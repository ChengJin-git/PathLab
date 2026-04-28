import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { AnnotationListPanel } from '@renderer/components/wsiViewer/AnnotationListPanel'
import type { AnnotationRegion, AnnotationsMap } from '@renderer/api/annotation'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => params ? `${key} ${JSON.stringify(params)}` : key,
  }),
}))

vi.mock('@renderer/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function region(id: string, label: string): AnnotationRegion {
  return {
    id,
    label,
    type: 'rect',
    x: 0,
    y: 0,
    width: 10,
    height: 10,
    points: [],
    color: '#ef4444',
  }
}

const annotations: AnnotationsMap = {
  wsi1: [region('r1', 'A'), region('r2', 'B'), region('r3', 'A')],
  wsi2: [region('r4', 'C')],
}

const baseProps = {
  currentWsiId: 'wsi1',
  regions: annotations.wsi1,
  allAnnotations: annotations,
  labelColors: { A: '#ef4444', B: '#22c55e', C: '#3b82f6' },
  focusedRegionId: null,
  canCreateDataset: true,
  currentLabel: 'A',
  visibleLabels: ['A', 'B', 'C'],
  missingCurrentLabel: false,
  onCurrentLabelChange: vi.fn(),
  onCreateLabel: vi.fn(),
  onRenameLabel: vi.fn(),
  onDeleteLabel: vi.fn(),
  onFocusRegion: vi.fn(),
  onUpdateRegion: vi.fn(),
  onDeleteRegion: vi.fn(),
  onDeleteRegions: vi.fn(),
  onDeleteCrossSlideByLabel: vi.fn(),
  onCreateDataset: vi.fn(),
}

describe('AnnotationListPanel label management', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to label name management before annotation counts', () => {
    render(<AnnotationListPanel {...baseProps} />)

    expect(screen.getByRole('button', { name: 'annotation.labelManagement' })).toHaveClass('bg-indigo-50')
    expect(screen.queryByText('annotation.noLabels')).not.toBeInTheDocument()
    expect(screen.queryByText('annotation.currentSlide')).not.toBeInTheDocument()
  })

  it('shows annotation counts on the annotation list tab', () => {
    render(<AnnotationListPanel {...baseProps} />)

    fireEvent.click(screen.getByRole('button', { name: 'annotation.annotationList' }))

    expect(screen.getByText('annotation.currentSlide')).toBeInTheDocument()
    expect(screen.getByText('annotation.crossSlideSummary')).toBeInTheDocument()
  })

  it('shows label management counts separately from annotation list counts', () => {
    render(<AnnotationListPanel {...baseProps} />)

    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
    expect(screen.getByText('C')).toBeInTheDocument()
    expect(screen.getByText('2 annotation.regions')).toBeInTheDocument()
    expect(screen.getByText('1 annotation.regions')).toBeInTheDocument()
    expect(screen.getByText('0 annotation.regions')).toBeInTheDocument()
  })

  it('renames a label from the side panel', () => {
    const onRenameLabel = vi.fn()
    render(<AnnotationListPanel {...baseProps} onRenameLabel={onRenameLabel} />)

    fireEvent.click(screen.getByRole('button', { name: 'annotation.renameLabel A' }))
    fireEvent.change(screen.getByDisplayValue('A'), { target: { value: 'Tumor' } })
    fireEvent.keyDown(screen.getByDisplayValue('Tumor'), { key: 'Enter' })

    expect(onRenameLabel).toHaveBeenCalledWith('A', 'Tumor')
  })

  it('clears the current label when clicking the highlighted label again', () => {
    const onCurrentLabelChange = vi.fn()
    render(<AnnotationListPanel {...baseProps} onCurrentLabelChange={onCurrentLabelChange} />)

    fireEvent.click(screen.getAllByRole('button', { name: /^A/ })[0])

    expect(onCurrentLabelChange).toHaveBeenCalledWith('')
  })

  it('confirms deletion of a used label before deleting its annotations', () => {
    const onDeleteLabel = vi.fn()
    render(<AnnotationListPanel {...baseProps} onDeleteLabel={onDeleteLabel} />)

    fireEvent.click(screen.getByRole('button', { name: 'annotation.deleteLabel A' }))

    expect(screen.getByText('annotation.confirmDeleteLabelWithRegions {"label":"A","count":2}')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'common.delete' }))

    expect(onDeleteLabel).toHaveBeenCalledWith('A')
  })

  it('persists the selected tab in localStorage', () => {
    const { unmount } = render(<AnnotationListPanel {...baseProps} />)

    fireEvent.click(screen.getByRole('button', { name: 'annotation.annotationList' }))
    expect(localStorage.getItem('annotationListPanelActiveTab')).toBe('annotationList')

    unmount()
    render(<AnnotationListPanel {...baseProps} />)

    expect(screen.getByRole('button', { name: 'annotation.annotationList' })).toHaveClass('bg-indigo-50')
    expect(screen.getByText('annotation.currentSlide')).toBeInTheDocument()
  })

  it('falls back to label name management for invalid stored tabs', () => {
    localStorage.setItem('annotationListPanelActiveTab', 'labels')

    render(<AnnotationListPanel {...baseProps} />)

    expect(screen.getByRole('button', { name: 'annotation.labelManagement' })).toHaveClass('bg-indigo-50')
    expect(screen.queryByText('annotation.currentSlide')).not.toBeInTheDocument()
  })
})
