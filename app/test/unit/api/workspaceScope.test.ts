import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildAuthHeaders,
  clearAuthToken,
  setAuthToken,
} from '@renderer/api/client'
import {
  getWorkspaceSelection,
  resetWorkspaceSelection,
  setWorkspaceSelection,
} from '@renderer/lib/workspaceSelection'

beforeEach(() => {
  resetWorkspaceSelection()
  setAuthToken('test-token')
})

describe('workspace request scope', () => {
  it('sends a scoped read-only policy and selected skills', () => {
    setWorkspaceSelection({
      workspaceId: 'ws-1',
      executionMode: 'read_only',
      expertId: null,
      enabledSkills: ['data'],
      enabledConnectors: [],
    })
    const headers = buildAuthHeaders()
    expect(headers.get('X-Workspace-ID')).toBe('ws-1')
    expect(headers.get('X-Workspace-Mode')).toBe('read_only')
    expect(headers.get('X-Chat-Skills')).toBe('["data"]')
  })

  it('clears the scope on logout instead of carrying it to the next account', () => {
    setWorkspaceSelection({
      workspaceId: 'private',
      executionMode: 'standard',
      expertId: null,
      enabledSkills: [],
      enabledConnectors: [],
    })
    clearAuthToken()
    expect(getWorkspaceSelection().workspaceId).toBeNull()
    expect(buildAuthHeaders().has('X-Workspace-ID')).toBe(false)
  })

  it('does not add a resource restriction for all areas', () => {
    expect(buildAuthHeaders().has('X-Workspace-ID')).toBe(false)
  })
})
