import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { RegisterRequestModal } from '@renderer/components/RegisterRequestModal'

const mocks = vi.hoisted(() => ({
  requestAccess: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@renderer/api/auth', () => ({
  requestAccess: mocks.requestAccess,
}))

vi.mock('@renderer/api/client', () => ({
  ApiError: class ApiError extends Error {
    details?: unknown
  },
}))

vi.mock('@renderer/components/TencentCaptcha', () => ({
  TencentCaptcha: ({ onVerify }: { onVerify: (ticket: string, randstr: string) => void }) => (
    <div>
      <button type="button" onClick={() => onVerify('ticket-only', '')}>Incomplete Tencent Captcha</button>
      <button type="button" onClick={() => onVerify('ticket-123', 'rand-456')}>Complete Tencent Captcha</button>
    </div>
  ),
}))

describe('RegisterRequestModal', () => {
  beforeEach(() => {
    mocks.requestAccess.mockReset()
  })

  it('keeps submit disabled until Tencent captcha returns both ticket and randstr', async () => {
    const user = userEvent.setup()

    render(
      <RegisterRequestModal
        isOpen
        onClose={vi.fn()}
        captchaProvider="tencent"
        captchaSiteKey="tencent-app-id"
      />,
    )

    const submit = screen.getByRole('button', { name: 'registerModal.submit' })
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Incomplete Tencent Captcha' }))
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Complete Tencent Captcha' }))
    expect(submit).toBeEnabled()
  })

  it('submits Tencent captcha ticket and randstr with the access request', async () => {
    mocks.requestAccess.mockResolvedValue({})
    const user = userEvent.setup()

    render(
      <RegisterRequestModal
        isOpen
        onClose={vi.fn()}
        captchaProvider="tencent"
        captchaSiteKey="tencent-app-id"
      />,
    )

    await user.type(screen.getByLabelText('registerModal.username'), 'alice')
    await user.type(screen.getByLabelText('registerModal.password'), 'secret1')
    await user.type(screen.getByLabelText('registerModal.confirmPassword'), 'secret1')
    await user.type(screen.getByLabelText('registerModal.educationalEmail'), 'alice@university.edu')
    await user.click(screen.getByRole('button', { name: 'Complete Tencent Captcha' }))
    await user.click(screen.getByRole('button', { name: 'registerModal.submit' }))

    expect(mocks.requestAccess).toHaveBeenCalledWith(expect.objectContaining({
      username: 'alice',
      registration_email: 'alice@university.edu',
      tencent_captcha_token: 'ticket-123',
      tencent_captcha_randstr: 'rand-456',
    }))
  })
})
