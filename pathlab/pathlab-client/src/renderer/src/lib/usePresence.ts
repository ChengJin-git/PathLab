import { useEffect, useRef, useCallback, useState } from 'react'
import { getPresenceWSUrl } from '../api/annotation'

export interface RemoteCursor {
  user_id: string
  nickname: string
  wsi_id: string
  x: number
  y: number
}

interface PresenceMsg {
  type: 'cursor' | 'join' | 'leave'
  user_id?: string
  nickname?: string
  wsi_id?: string
  x?: number
  y?: number
}

export function usePresence(datasetId: string | null) {
  const [cursors, setCursors] = useState<Record<string, RemoteCursor>>({})
  const wsRef = useRef<WebSocket | null>(null)
  const throttleRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingCursorRef = useRef<{ wsiId: string; x: number; y: number } | null>(null)

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

  return { cursors, sendCursor }
}
