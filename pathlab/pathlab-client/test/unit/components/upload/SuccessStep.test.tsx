import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SuccessStep } from '../../../../src/renderer/src/components/upload/SuccessStep'

vi.mock('react-i18next', async importOriginal => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) => key,
    }),
  }
})

describe('SuccessStep', () => {
  it('centers content vertically without negative top margin', () => {
    render(
      <SuccessStep
        datasetName="Test Dataset"
        splitUploadSuccess={null}
        fromAIChat={false}
        onNavigate={vi.fn()}
        onReset={vi.fn()}
      />,
    )

    const root = screen.getByTestId('success-step-root')
    expect(root).not.toBeNull()
    const className = root?.className ?? ''
    expect(className).toContain('justify-center')
    expect(className).not.toContain('-mt-')
  })
})
