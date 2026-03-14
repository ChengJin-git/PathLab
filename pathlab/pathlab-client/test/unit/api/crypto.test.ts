import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { sha256, APP_SALT } from '@renderer/api/crypto'

describe('APP_SALT', () => {
  it('is a non-empty string', () => {
    expect(typeof APP_SALT).toBe('string')
    expect(APP_SALT.length).toBeGreaterThan(0)
  })

  it('matches expected application salt value', () => {
    expect(APP_SALT).toBe('PathLab2024SecureSalt')
  })
})

describe('sha256 (Web Crypto API path)', () => {
  it('returns a 64-character lowercase hex string', async () => {
    const hash = await sha256('hello')
    expect(hash).toHaveLength(64)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })

  it('produces the known SHA-256 hash for "hello"', async () => {
    const hash = await sha256('hello')
    expect(hash).toBe('2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824')
  })

  it('produces different hashes for different inputs', async () => {
    const h1 = await sha256('pathlab')
    const h2 = await sha256('PATHLAB')
    expect(h1).not.toBe(h2)
  })

  it('produces consistent results across repeated calls', async () => {
    const h1 = await sha256('consistent')
    const h2 = await sha256('consistent')
    expect(h1).toBe(h2)
  })

  it('handles empty string', async () => {
    const hash = await sha256('')
    expect(hash).toHaveLength(64)
    expect(hash).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
  })

  it('handles unicode input', async () => {
    const hash = await sha256('病理学')
    expect(hash).toHaveLength(64)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe('sha256 (JavaScript fallback path)', () => {
  let originalCrypto: Crypto

  beforeEach(() => {
    originalCrypto = globalThis.crypto
    Object.defineProperty(globalThis, 'crypto', {
      value: undefined,
      writable: true,
      configurable: true,
    })
  })

  afterEach(() => {
    Object.defineProperty(globalThis, 'crypto', {
      value: originalCrypto,
      writable: true,
      configurable: true,
    })
  })

  it('returns a 64-character hex string via fallback', async () => {
    const hash = await sha256('hello')
    expect(hash).toHaveLength(64)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })

  it('fallback produces a consistent 64-character hex hash', async () => {
    const fallbackHash = await sha256('hello')
    expect(fallbackHash).toHaveLength(64)
    expect(fallbackHash).toMatch(/^[0-9a-f]{64}$/)
  })

  it('fallback handles empty string and returns a 64-character hex hash', async () => {
    const hash = await sha256('')
    expect(hash).toHaveLength(64)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe('sha256 (subtle.digest failure fallback)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', {
      subtle: {
        digest: vi.fn().mockRejectedValue(new Error('SubtleCrypto not supported')),
      },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('falls back to pure-JS implementation when subtle.digest throws', async () => {
    const hash = await sha256('hello')
    expect(hash).toHaveLength(64)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })
})
