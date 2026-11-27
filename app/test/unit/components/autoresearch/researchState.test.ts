import { describe, expect, it } from 'vitest'
import { researchStatus, isPublicResearchMessage } from '@renderer/components/autoresearch/researchState'

describe('authoritative research status', () => {
  it('never lets an old queued event overwrite a completed snapshot', () => {
    expect(researchStatus({ session_id: 's', question: 'Download', status: 'completed', sequence: 12 }, [{ kind: 'state', seq: 1, status: 'queued' }])).toBe('completed')
  })
  it('accepts a state event newer than the snapshot', () => {
    expect(researchStatus({ session_id: 's', question: 'Download', status: 'running', sequence: 12 }, [{ kind: 'state', seq: 13, status: 'blocked' }])).toBe('blocked')
  })
  it('hides supervisor messages even if the native API omitted metadata', () => {
    expect(isPublicResearchMessage({ type: 'user' })).toBe(false)
    expect(isPublicResearchMessage({ type: 'synthetic' })).toBe(false)
    expect(isPublicResearchMessage({ type: 'assistant' })).toBe(true)
  })
})
