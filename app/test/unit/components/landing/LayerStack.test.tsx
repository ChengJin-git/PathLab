import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

import { LayerStack } from '@renderer/components/landing/LayerStack'

describe('LayerStack', () => {
  it('shows the overlaid view by default and separates the layers on request', () => {
    const { container } = render(<LayerStack />)
    const stack = screen.getByRole('group', { name: 'publicExperience.layerStackLabel' })
    expect(container.querySelectorAll('.layer-stack__plane')).toHaveLength(3)
    expect(container.querySelectorAll('.layer-stack__plane--annotations path').length).toBeGreaterThan(0)
    expect(stack).not.toHaveAttribute('data-open')
    fireEvent.keyDown(stack, { key: 'Enter' })
    expect(stack).toHaveAttribute('data-open', 'true')
    fireEvent.click(stack)
    expect(stack).not.toHaveAttribute('data-open')
  })
})
