import { useState, useCallback } from 'react'

export function useAsyncAction<T = void>(options?: {
  onError?: (err: unknown) => void
}): [isPending: boolean, run: (fn: () => Promise<T>) => Promise<T | undefined>] {
  const [pendingCount, setPendingCount] = useState(0)
  const onError = options?.onError ?? ((err) => console.error(err))

  const run = useCallback(
    async (fn: () => Promise<T>): Promise<T | undefined> => {
      setPendingCount((c) => c + 1)
      try {
        return await fn()
      } catch (err) {
        onError(err)
        return undefined
      } finally {
        setPendingCount((c) => c - 1)
      }
    },
    [onError]
  )

  return [pendingCount > 0, run]
}
