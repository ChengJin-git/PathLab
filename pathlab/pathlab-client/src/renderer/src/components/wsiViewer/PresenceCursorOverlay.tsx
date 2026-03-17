import { useEffect, useRef, useCallback } from 'react'
import type { RemoteCursor } from '../../lib/usePresence'

interface Props {
  viewer: any
  wsiId: string
  cursors: Record<string, RemoteCursor>
  enabled: boolean
}

const CURSOR_COLORS = ['#6366f1','#ec4899','#10b981','#f59e0b','#3b82f6','#ef4444','#8b5cf6','#14b8a6']

function colorForUserId(userId: string): string {
  let hash = 0
  for (let i = 0; i < userId.length; i++) hash = (hash * 31 + userId.charCodeAt(i)) >>> 0
  return CURSOR_COLORS[hash % CURSOR_COLORS.length]
}

export function PresenceCursorOverlay({ viewer, wsiId, cursors, enabled }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const redraw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !viewer?.viewport) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const container = viewer.container
    if (container) {
      canvas.width = container.clientWidth
      canvas.height = container.clientHeight
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    const visibleCursors = Object.values(cursors).filter(c => c.wsi_id === wsiId)
    for (const cursor of visibleCursors) {
      const pixel = viewer.viewport.pixelFromPoint(
        new (window as any).OpenSeadragon.Point(cursor.x, cursor.y)
      )
      if (!pixel) continue
      const { x, y } = pixel
      if (x < -20 || y < -20 || x > canvas.width + 20 || y > canvas.height + 20) continue

      const color = colorForUserId(cursor.user_id)

      ctx.save()
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x + 10, y + 14)
      ctx.lineTo(x + 4, y + 12)
      ctx.lineTo(x + 6, y + 18)
      ctx.lineTo(x + 3, y + 19)
      ctx.lineTo(x + 1, y + 13)
      ctx.lineTo(x - 4, y + 16)
      ctx.closePath()
      ctx.fillStyle = color
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 1.5
      ctx.stroke()

      const label = cursor.nickname.slice(0, 12)
      ctx.font = '11px system-ui, sans-serif'
      const metrics = ctx.measureText(label)
      const lx = x + 12
      const ly = y + 14
      ctx.fillStyle = color
      ctx.beginPath()
      // @ts-ignore roundRect is available in modern browsers
      if (ctx.roundRect) {
        // @ts-ignore
        ctx.roundRect(lx - 2, ly - 11, metrics.width + 8, 16, 4)
      } else {
        ctx.rect(lx - 2, ly - 11, metrics.width + 8, 16)
      }
      ctx.fill()
      ctx.fillStyle = '#fff'
      ctx.fillText(label, lx + 2, ly)
      ctx.restore()
    }
  }, [viewer, wsiId, cursors])

  useEffect(() => {
    redraw()
  }, [redraw])

  useEffect(() => {
    if (!viewer) return
    viewer.addHandler('animation', redraw)
    viewer.addHandler('animation-finish', redraw)
    viewer.addHandler('resize', redraw)
    return () => {
      try {
        viewer.removeHandler('animation', redraw)
        viewer.removeHandler('animation-finish', redraw)
        viewer.removeHandler('resize', redraw)
      } catch { /* viewer may be destroyed */ }
    }
  }, [viewer, redraw])

  if (!enabled) return null

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 10,
      }}
    />
  )
}
