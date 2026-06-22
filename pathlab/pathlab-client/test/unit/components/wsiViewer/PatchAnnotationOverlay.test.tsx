import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { PatchAnnotationOverlay } from '@renderer/components/wsiViewer/PatchAnnotationOverlay'

function installSvgGeometryMocks() {
  Object.defineProperty(SVGSVGElement.prototype, 'getScreenCTM', {
    configurable: true,
    value: () => ({ inverse: () => ({}) }),
  })
  Object.defineProperty(SVGSVGElement.prototype, 'createSVGPoint', {
    configurable: true,
    value: () => ({
      x: 0,
      y: 0,
      matrixTransform(this: { x: number; y: number }) {
        return { x: this.x, y: this.y }
      },
    }),
  })
}

describe('PatchAnnotationOverlay cancel/undo behavior', () => {
  beforeEach(() => {
    installSvgGeometryMocks()
  })

  it('cancels an in-progress polygon on Escape without creating annotation', () => {
    const onRegionCreated = vi.fn()

    const { container } = render(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
      />,
    )

    const svg = container.querySelector('svg') as SVGSVGElement
    fireEvent.click(svg, { clientX: 100, clientY: 100 })
    fireEvent.click(svg, { clientX: 300, clientY: 100 })
    fireEvent.click(svg, { clientX: 300, clientY: 300 })

    fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' })
    fireEvent.doubleClick(svg)

    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('removes the last pending polygon point on Backspace/Delete', () => {
    const onRegionCreated = vi.fn()

    const { container } = render(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
      />,
    )

    const svg = container.querySelector('svg') as SVGSVGElement
    fireEvent.click(svg, { clientX: 100, clientY: 100 })
    fireEvent.click(svg, { clientX: 300, clientY: 100 })
    fireEvent.click(svg, { clientX: 300, clientY: 300 })
    fireEvent.click(svg, { clientX: 100, clientY: 300 })

    fireEvent.keyDown(window, { key: 'Backspace', code: 'Backspace' })
    fireEvent.keyDown(window, { key: 'Delete', code: 'Delete' })
    fireEvent.doubleClick(svg)

    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('cancels in-progress polygon when cancelToken changes', () => {
    const onRegionCreated = vi.fn()

    const { container, rerender } = render(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
        cancelToken={1}
      />,
    )

    const svg = container.querySelector('svg') as SVGSVGElement
    fireEvent.click(svg, { clientX: 100, clientY: 100 })
    fireEvent.click(svg, { clientX: 300, clientY: 100 })
    fireEvent.click(svg, { clientX: 300, clientY: 300 })

    rerender(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="polygon"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
        cancelToken={2}
      />,
    )

    fireEvent.doubleClick(svg)
    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('cancels an in-progress rectangle drag on Escape without creating annotation', () => {
    const onRegionCreated = vi.fn()

    const { container } = render(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
      />,
    )

    const svg = container.querySelector('svg') as SVGSVGElement
    fireEvent.mouseDown(svg, { clientX: 100, clientY: 100 })
    fireEvent.mouseMove(svg, { clientX: 260, clientY: 260 })
    fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' })
    fireEvent.mouseUp(svg, { clientX: 260, clientY: 260 })

    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('cancels in-progress rectangle drag when cancelToken changes', () => {
    const onRegionCreated = vi.fn()

    const { container, rerender } = render(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
        cancelToken={1}
      />,
    )

    const svg = container.querySelector('svg') as SVGSVGElement
    fireEvent.mouseDown(svg, { clientX: 100, clientY: 100 })
    fireEvent.mouseMove(svg, { clientX: 260, clientY: 260 })

    rerender(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
        cancelToken={2}
      />,
    )

    fireEvent.mouseUp(svg, { clientX: 260, clientY: 260 })
    expect(onRegionCreated).not.toHaveBeenCalled()
  })

  it('keeps normal rectangle creation unchanged', () => {
    const onRegionCreated = vi.fn()

    const { container } = render(
      <PatchAnnotationOverlay
        regions={[]}
        labelColors={{}}
        slideWidth={1000}
        slideHeight={1000}
        annotationMode
        drawingTool="rect"
        currentLabel="Tumor"
        currentColor="#ef4444"
        onRegionCreated={onRegionCreated}
      />,
    )

    const svg = container.querySelector('svg') as SVGSVGElement
    fireEvent.mouseDown(svg, { clientX: 100, clientY: 100 })
    fireEvent.mouseMove(svg, { clientX: 220, clientY: 250 })
    fireEvent.mouseUp(svg, { clientX: 220, clientY: 250 })

    expect(onRegionCreated).toHaveBeenCalledTimes(1)
    expect(onRegionCreated).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'rect', x: 100, y: 100, width: 120, height: 150 }),
    )
  })
})
