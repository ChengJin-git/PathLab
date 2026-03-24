import { useState, useEffect } from 'react'

export function useDraftState<T>(key: string, initialValue: T) {
  const [state, setState] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(key)
      if (raw !== null) return JSON.parse(raw) as T
    } catch {}
    return initialValue
  })

  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(state))
    } catch {}
  }, [key, state])

  return [state, setState] as const
}

export function clearDraftKeys(prefix: string): void {
  try {
    const toRemove = Object.keys(sessionStorage).filter((k) => k.startsWith(prefix))
    for (const k of toRemove) {
      sessionStorage.removeItem(k)
    }
  } catch {}
}
