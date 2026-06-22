import { describe, expect, it } from 'vitest'
import { isPathScientistStandaloneMode } from '@renderer/lib/pathscientistStandalone'

describe('isPathScientistStandaloneMode', () => {
  it('enables standalone mode for browser PathScientist debug sessions', () => {
    expect(isPathScientistStandaloneMode({ isElectron: false, env: { VITE_DEBUG: 'true' } })).toBe(true)
  })

  it('enables standalone mode through an explicit environment flag', () => {
    expect(isPathScientistStandaloneMode({ isElectron: false, env: { VITE_PATHSCIENTIST_STANDALONE: 'true' } })).toBe(true)
  })

  it('keeps Electron and normal production browser builds in full PathLab mode', () => {
    expect(isPathScientistStandaloneMode({ isElectron: true, env: { VITE_DEBUG: 'true' } })).toBe(false)
    expect(isPathScientistStandaloneMode({ isElectron: false, env: {} })).toBe(false)
  })
})
