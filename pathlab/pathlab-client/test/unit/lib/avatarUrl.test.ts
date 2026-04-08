import { describe, expect, it, vi } from 'vitest'

vi.mock('../../../src/renderer/src/config', () => ({
  API_BASE: 'http://127.0.0.1:6100/api'
}))

import { resolveAvatarUrl } from '../../../src/renderer/src/lib/avatarUrl'

describe('resolveAvatarUrl', () => {
  it('returns null for empty values', () => {
    expect(resolveAvatarUrl(null)).toBeNull()
    expect(resolveAvatarUrl(undefined)).toBeNull()
    expect(resolveAvatarUrl('')).toBeNull()
  })

  it('preserves absolute avatar urls', () => {
    expect(resolveAvatarUrl('https://cdn.example.com/avatar.jpg')).toBe('https://cdn.example.com/avatar.jpg')
  })

  it('prefixes root-relative avatar urls with API_BASE', () => {
    expect(resolveAvatarUrl('/avatars/user.jpg?t=1')).toBe('http://127.0.0.1:6100/avatars/user.jpg?t=1')
  })
})
