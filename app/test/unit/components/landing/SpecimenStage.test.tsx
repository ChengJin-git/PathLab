import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@renderer/components/landing/specimen/engine', () => ({ getSpecimenEngine: () => null }))

import { SpecimenStage } from '@renderer/components/landing/specimen/SpecimenStage'

describe('SpecimenStage', () => {
  it('keeps a labelled backdrop and no controls when WebGL2 is unavailable', () => {
    render(<SpecimenStage />)
    expect(screen.getByRole('img', { name: 'publicExperience.stageLabel' })).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
    expect(document.querySelector('canvas')).toBeNull()
  })
})
