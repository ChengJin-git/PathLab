import { describe, expect, it } from 'vitest'
import { isAutoResearchStandaloneMode } from '@renderer/lib/autoresearchStandalone'

describe('isAutoResearchStandaloneMode', () => {
  it('enables standalone mode for browser AutoResearch debug sessions', () => {
    expect(isAutoResearchStandaloneMode({ isElectron: false, env: { VITE_DEBUG: 'true' } })).toBe(true)
  })

  it('enables standalone mode through an explicit environment flag', () => {
    expect(isAutoResearchStandaloneMode({ isElectron: false, env: { VITE_AUTORESEARCH_STANDALONE: 'true' } })).toBe(true)
  })

  it('keeps Electron and normal production browser builds in full PathLab mode', () => {
    expect(isAutoResearchStandaloneMode({ isElectron: true, env: { VITE_DEBUG: 'true' } })).toBe(false)
    expect(isAutoResearchStandaloneMode({ isElectron: false, env: {} })).toBe(false)
  })
})
