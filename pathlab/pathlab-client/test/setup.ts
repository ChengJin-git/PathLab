import '@testing-library/jest-dom'
import { vi, beforeEach } from 'vitest'

vi.stubGlobal('fetch', vi.fn())

beforeEach(() => {
  vi.mocked(fetch).mockReset()
  localStorage.clear()
})
