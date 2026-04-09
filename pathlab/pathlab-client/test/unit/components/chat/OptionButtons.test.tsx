import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { OptionButtons } from '@renderer/components/chat/OptionButtons'

describe('OptionButtons', () => {
  it('does not allow selecting options while a response is still generating', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()

    render(
      <OptionButtons
        options={[{ text: '阅读全文' }]}
        onSelect={onSelect}
        disabled
      />,
    )

    await user.click(screen.getByRole('button', { name: '阅读全文' }))

    expect(onSelect).not.toHaveBeenCalled()
  })
})
