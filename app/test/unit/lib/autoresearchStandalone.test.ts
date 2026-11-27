import { describe, expect, it } from 'vitest'
import { isAutoResearchStandaloneMode } from '@renderer/lib/autoresearchStandalone'

describe('isAutoResearchStandaloneMode', () => {
  it('enables standalone mode for AutoResearch debug sessions', () => {
    expect(isAutoResearchStandaloneMode({ VITE_DEBUG: 'true' })).toBe(true)
  })

  it('enables standalone mode through an explicit environment flag', () => {
    expect(isAutoResearchStandaloneMode({ VITE_AUTORESEARCH_STANDALONE: 'true' })).toBe(true)
  })

  it('keeps normal production builds in full PathLab mode', () => {
    expect(isAutoResearchStandaloneMode({})).toBe(false)
  })
})
