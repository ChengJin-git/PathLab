import { useState, useCallback } from 'react'

interface AsyncActionOptions {
  onError?: (err: unknown) => void
  withError?: boolean
}

// Overloads for type safety
export function useAsyncAction<T = void>(options: AsyncActionOptions & { withError: true }): [
  isPending: boolean,
  run: (fn: () => Promise<T>) => Promise<T | undefined>,
  error: string | null,
  clearError: () => void
]
export function useAsyncAction<T = void>(options?: AsyncActionOptions & { withError?: false | undefined }): [
  isPending: boolean,
  run: (fn: () => Promise<T>) => Promise<T | undefined>
]
export function useAsyncAction<T = void>(
  options?: AsyncActionOptions
): [boolean, (fn: () => Promise<T>) => Promise<T | undefined>] | 
   [boolean, (fn: () => Promise<T>) => Promise<T | undefined>, string | null, () => void] {
  const [pendingCount, setPendingCount] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const handleError = useCallback((err: unknown) => {
    const message = err instanceof Error ? err.message : String(err)
    if (options?.withError) {
      setError(message)
    }
    if (options?.onError) {
      options.onError(err)
    } else if (!options?.withError) {
      console.error(err)
    }
  }, [options?.withError, options?.onError])

  const clearError = useCallback(() => setError(null), [])

  const run = useCallback(
    async (fn: () => Promise<T>): Promise<T | undefined> => {
      setPendingCount((c) => c + 1)
      if (options?.withError) setError(null)
      try {
        return await fn()
      } catch (err) {
        handleError(err)
        return undefined
      } finally {
        setPendingCount((c) => c - 1)
      }
    },
    [handleError, options?.withError]
  )

  if (options?.withError) {
    return [pendingCount > 0, run, error, clearError]
  }
  return [pendingCount > 0, run]
}
