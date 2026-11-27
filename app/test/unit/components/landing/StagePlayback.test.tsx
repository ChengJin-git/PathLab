import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const engine = vi.hoisted(() => ({ paused: false, setPaused: vi.fn(), isPaused: () => false, onProgress: vi.fn(() => () => {}) }))
vi.mock('@renderer/components/landing/specimen/engine', () => ({ getSpecimenEngine: () => engine }))

import { StagePlayback } from '@renderer/components/landing/specimen/StagePlayback'

describe('StagePlayback', () => {
  it('is a labelled toggle that pauses the shared stage', () => {
    render(<StagePlayback />)
    const button = screen.getByRole('button', { name: 'publicExperience.stagePause' })
    fireEvent.click(button)
    expect(engine.setPaused).toHaveBeenCalledWith(true)
    expect(screen.getByRole('button', { name: 'publicExperience.stagePlay' })).toHaveAttribute('aria-pressed', 'true')
    expect(engine.onProgress).toHaveBeenCalled()
  })
})
