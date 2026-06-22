import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { AnnotationOverlay } from '@renderer/components/wsiViewer/AnnotationOverlay'

type ViewerMock = {
  viewport: {
    pointFromPixel: (point: { x: number; y: number }) => { x: number; y: number }
    pixelFromPoint: (point: { x: number; y: number }) => { x: number; y: number }
    zoomBy: ReturnType<typeof vi.fn>
    applyConstraints: ReturnType<typeof vi.fn>
  }
  world: { getItemCount: () => number }
  addHandler: ReturnType<typeof vi.fn>
  removeHandler: ReturnType<typeof vi.fn>
  setMouseNavEnabled: ReturnType<typeof vi.fn>
}

function createViewerMock(): ViewerMock {
  return {
    viewport: {
      pointFromPixel: (point) => ({ x: point.x / 1000, y: point.y / 1000 }),
      pixelFromPoint: (point) => ({ x: point.x * 1000, y: point.y * 1000 }),
      zoomBy: vi.fn(),
      applyConstraints: vi.fn(),
    },
    world: { getItemCount: () => 1 },
    addHandler: vi.fn(),
    removeHandler: vi.fn(),
    setMouseNavEnabled: vi.fn(),
  }
}

function createContextMock(): CanvasRenderingContext2D {
  const fn = vi.fn
  return {
    clearRect: fn(),
    beginPath: fn(),
    moveTo: fn(),
    lineTo: fn(),
    closePath: fn(),
    stroke: fn(),
    fill: fn(),
    fillRect: fn(),
    strokeRect: fn(),
    setLineDash: fn(),
    arc: fn(),
    save: fn(),
    restore: fn(),
    measureText: vi.fn(() => ({ width: 10 } as TextMetrics)),
    quadraticCurveTo: fn(),
    fillText: fn(),
    strokeStyle: '#000',
    lineWidth: 1,
    fillStyle: '#000',
    font: '10px sans-serif',
    globalAlpha: 1,
    shadowColor: 'transparent',
    shadowBlur: 0,
    shadowOffsetY: 0,
  } as unknown as CanvasRenderingContext2D
}

describe('AnnotationOverlay polygon cancel/undo', () => {
  beforeEach(() => {
    const context = createContextMock()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
    vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      width: 1000,
      height: 1000,
      right: 1000,
      bottom: 1000,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })

    ;(window as unknown as { OpenSeadragon: { Point: new (x: number, y: number) => { x: number; y: number } } }).OpenSeadragon = {
      Point: class {
        x: number
        y: number
        constructor(x: number, y: number) {
          this.x = x
          this.y = y
        }
      },
    }
  })

  it('cancels an in-progress polygon on Escape without creating annotation', () => {
    const onRegionCreated = vi.fn()
    const viewer = createViewerMock()

    const { container } = render(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
      />,
    )

    const canvas = container.querySelector('canvas') as HTMLCanvasElement
    fireEvent.click(canvas, { clientX: 100, clientY: 100 })
    fireEvent.click(canvas, { clientX: 300, clientY: 100 })
    fireEvent.click(canvas, { clientX: 300, clientY: 300 })

    fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' })
    fireEvent.doubleClick(canvas)

    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('removes the last pending polygon point on Backspace/Delete', () => {
    const onRegionCreated = vi.fn()
    const viewer = createViewerMock()

    const { container } = render(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
      />,
    )

    const canvas = container.querySelector('canvas') as HTMLCanvasElement
    fireEvent.click(canvas, { clientX: 100, clientY: 100 })
    fireEvent.click(canvas, { clientX: 300, clientY: 100 })
    fireEvent.click(canvas, { clientX: 300, clientY: 300 })
    fireEvent.click(canvas, { clientX: 100, clientY: 300 })

    fireEvent.keyDown(window, { key: 'Backspace', code: 'Backspace' })
    fireEvent.keyDown(window, { key: 'Delete', code: 'Delete' })
    fireEvent.doubleClick(canvas)

    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('keeps rectangle drawing behavior unchanged', () => {
    const onRegionCreated = vi.fn()
    const viewer = createViewerMock()

    const { container } = render(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
      />,
    )

    const canvas = container.querySelector('canvas') as HTMLCanvasElement
    fireEvent.mouseDown(canvas, { clientX: 100, clientY: 100 })
    fireEvent.mouseMove(canvas, { clientX: 220, clientY: 250 })
    fireEvent.mouseUp(canvas, { clientX: 220, clientY: 250 })

    expect(onRegionCreated).toHaveBeenCalledTimes(1)
    expect(onRegionCreated).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'rect', x: 100, y: 100, width: 120, height: 150 }),
    )
  })

  it('cancels in-progress polygon when cancelToken changes', () => {
    const onRegionCreated = vi.fn()
    const viewer = createViewerMock()

    const { container, rerender } = render(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
        cancelToken={1}
      />,
    )

    const canvas = container.querySelector('canvas') as HTMLCanvasElement
    fireEvent.click(canvas, { clientX: 100, clientY: 100 })
    fireEvent.click(canvas, { clientX: 300, clientY: 100 })
    fireEvent.click(canvas, { clientX: 300, clientY: 300 })

    rerender(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
        cancelToken={2}
      />,
    )

    fireEvent.doubleClick(canvas)
    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('cancels an in-progress rectangle drag on Escape without creating annotation', () => {
    const onRegionCreated = vi.fn()
    const viewer = createViewerMock()

    const { container } = render(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
      />,
    )

    const canvas = container.querySelector('canvas') as HTMLCanvasElement
    fireEvent.mouseDown(canvas, { clientX: 100, clientY: 100 })
    fireEvent.mouseMove(canvas, { clientX: 260, clientY: 260 })
    fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' })
    fireEvent.mouseUp(canvas, { clientX: 260, clientY: 260 })

    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('cancels in-progress rectangle drag when cancelToken changes', () => {
    const onRegionCreated = vi.fn()
    const viewer = createViewerMock()

    const { container, rerender } = render(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
        cancelToken={10}
      />,
    )

    const canvas = container.querySelector('canvas') as HTMLCanvasElement
    fireEvent.mouseDown(canvas, { clientX: 100, clientY: 100 })
    fireEvent.mouseMove(canvas, { clientX: 260, clientY: 260 })

    rerender(
      <AnnotationOverlay
        viewer={viewer}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        regions={[]}
        labelColors={{ Tumor: '#ef4444' }}
        slideWidth={1000}
        slideHeight={1000}
        onRegionCreated={onRegionCreated}
        cancelToken={11}
      />,
    )

    fireEvent.mouseUp(canvas, { clientX: 260, clientY: 260 })
    expect(onRegionCreated).not.toHaveBeenCalled()
  })
})
