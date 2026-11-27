import '@testing-library/jest-dom/vitest'
import { vi, beforeEach } from 'vitest'

const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
  configurable: true,
})

vi.stubGlobal('fetch', vi.fn())

beforeEach(() => {
  vi.mocked(fetch).mockReset()
  localStorage.clear()
})
