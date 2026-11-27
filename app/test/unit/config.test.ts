import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('API configuration', () => {
  it('honors explicit deployment URLs', async () => {
    vi.stubEnv('VITE_API_BASE', '/api')
    vi.stubEnv('VITE_PREPROCESSING_BASE', '/preprocessing')
    vi.stubEnv('VITE_AI_BASE', '/ai')
    const config = await import('@renderer/config')
    await config.initializeApiConfig()
    config.updateApiBase()
    expect([config.API_BASE, config.PREPROCESSING_BASE, config.AI_BASE]).toEqual(['/api', '/preprocessing', '/ai'])
  })

  it('falls back to the page host and the standard service ports', async () => {
    const config = await import('@renderer/config')
    config.updateApiBase()
    const host = window.location.hostname || '127.0.0.1'
    expect(config.API_BASE).toBe(`http://${host}:6100`)
    expect(config.PREPROCESSING_BASE).toBe(`http://${host}:6101`)
    expect(config.AI_BASE).toBe(`http://${host}:6102/api/ai`)
  })
})
