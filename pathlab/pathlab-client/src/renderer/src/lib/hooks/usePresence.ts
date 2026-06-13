import { useEffect, useRef, useCallback, useState } from 'react'
import { getPresenceWSUrl } from '../../api/annotation'
import type { AnnotationRegion } from '../../api/annotation'

export interface RemoteCursor {
  user_id: string
  nickname: string
  wsi_id: string
  x: number
  y: number
}

export type AnnotationPatchOp = 'add' | 'delete' | 'update'

export interface AnnotationPatchEvent {
  user_id: string
  wsi_id: string
  op: AnnotationPatchOp
  region?: AnnotationRegion
  region_id?: string
  region_updates?: Partial<AnnotationRegion>
}

interface PresenceMsg {
  type: 'cursor' | 'join' | 'leave' | 'annotation_patch'
  user_id?: string
  nickname?: string
  wsi_id?: string
  x?: number
  y?: number
  op?: AnnotationPatchOp
  region?: AnnotationRegion
  region_id?: string
  region_updates?: Partial<AnnotationRegion>
}

export function usePresence(
  datasetId: string | null,
  onAnnotationPatch?: (event: AnnotationPatchEvent) => void,
) {
  const [cursors, setCursors] = useState<Record<string, RemoteCursor>>({})
  const wsRef = useRef<WebSocket | null>(null)
  const throttleRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingCursorRef = useRef<{ wsiId: string; x: number; y: number } | null>(null)
  // Keep a stable ref to the callback so the ws.onmessage closure never goes stale
  const onAnnotationPatchRef = useRef(onAnnotationPatch)
  useEffect(() => { onAnnotationPatchRef.current = onAnnotationPatch }, [onAnnotationPatch])

  useEffect(() => {
    if (!datasetId) return
    const url = getPresenceWSUrl(datasetId)
    if (!url) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const msg: PresenceMsg = JSON.parse(event.data)
        if (msg.type === 'cursor' && msg.user_id) {
          setCursors(prev => ({
            ...prev,
            [msg.user_id!]: {
              user_id: msg.user_id!,
              nickname: msg.nickname || msg.user_id!,
              wsi_id: msg.wsi_id || '',
              x: msg.x ?? 0,
              y: msg.y ?? 0,
            },
          }))
        } else if (msg.type === 'leave' && msg.user_id) {
          setCursors(prev => {
            const next = { ...prev }
            delete next[msg.user_id!]
            return next
          })
        } else if (msg.type === 'annotation_patch' && msg.user_id && msg.op) {
          const op = msg.op
          if (op === 'add' && msg.region) {
            onAnnotationPatchRef.current?.({
              user_id: msg.user_id,
              wsi_id: msg.wsi_id || '',
              op: 'add',
              region: msg.region,
            })
          } else if (op === 'update' && msg.region_id && msg.region_updates) {
            onAnnotationPatchRef.current?.({
              user_id: msg.user_id,
              wsi_id: msg.wsi_id || '',
              op: 'update',
              region_id: msg.region_id,
              region_updates: msg.region_updates,
            })
          } else if (op === 'delete' && msg.region_id) {
            onAnnotationPatchRef.current?.({
              user_id: msg.user_id,
              wsi_id: msg.wsi_id || '',
              op: 'delete',
              region_id: msg.region_id,
            })
          }
        }
      } catch { /* ignore malformed */ }
    }

    ws.onclose = () => { wsRef.current = null }
    ws.onerror = () => {}

    return () => {
      ws.close()
      wsRef.current = null
      setCursors({})
    }
  }, [datasetId])

  const sendCursor = useCallback((wsiId: string, x: number, y: number) => {
    pendingCursorRef.current = { wsiId, x, y }
    if (throttleRef.current) return
    throttleRef.current = setTimeout(() => {
      throttleRef.current = null
      const pending = pendingCursorRef.current
      if (!pending) return
      pendingCursorRef.current = null
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'cursor', wsi_id: pending.wsiId, x: pending.x, y: pending.y }))
      }
    }, 80)
  }, [])

  const sendAnnotationPatch = useCallback((
    op: AnnotationPatchOp,
    wsiId: string,
    payload: { region?: AnnotationRegion; region_id?: string; region_updates?: Partial<AnnotationRegion> },
  ) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({
      type: 'annotation_patch',
      wsi_id: wsiId,
      op,
      ...payload,
    }))
  }, [])

  return { cursors, sendCursor, sendAnnotationPatch }
}
