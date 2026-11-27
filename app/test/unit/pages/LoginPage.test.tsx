import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import LoginPage from '@renderer/pages/LoginPage'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  getPublicSettings: vi.fn(),
}))

vi.mock('@renderer/contexts/AuthContext', () => ({
  useAuth: () => ({
    login: mocks.login,
    isLoading: false,
    error: null,
    isLoggedIn: false,
  }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@renderer/components/common/LanguageSwitcher', () => ({
  LanguageSwitcher: () => <button type="button">Lang</button>,
}))

vi.mock('@renderer/components/DisclaimerModal', () => ({ DisclaimerModal: () => null }))
vi.mock('@renderer/components/PrivacyPolicyModal', () => ({ PrivacyPolicyModal: () => null }))
vi.mock('@renderer/components/RegisterRequestModal', () => ({ RegisterRequestModal: () => null }))
vi.mock('@renderer/components/TencentCaptcha', () => ({
  TencentCaptcha: ({ onVerify }: { onVerify: (ticket: string, randstr: string) => void }) => (
    <div>
      <button type="button" onClick={() => onVerify('ticket-only', '')}>Incomplete Tencent Captcha</button>
      <button type="button" onClick={() => onVerify('ticket-123', 'rand-456')}>Complete Tencent Captcha</button>
    </div>
  ),
}))
vi.mock('@renderer/components/landing/LoginShowcase', () => ({ LoginShowcase: () => null }))
vi.mock('@renderer/api', () => ({
  getPublicSettings: mocks.getPublicSettings,
  ApiError: class ApiError extends Error {},
}))

describe('LoginPage', () => {
  beforeEach(() => {
    mocks.login.mockReset()
    mocks.getPublicSettings.mockResolvedValue({ captcha_provider: null, captcha_site_key: '' })
  })

  it('labels credentials and lets users reveal a password without submitting', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(await screen.findByLabelText('auth.username')).toHaveAttribute('autocomplete', 'username')
    const password = screen.getByLabelText('auth.password')
    await user.type(password, 'secret')
    await user.click(screen.getByRole('button', { name: 'publicExperience.showPassword' }))
    expect(password).toHaveAttribute('type', 'text')
    expect(password).toHaveValue('secret')
    await user.click(screen.getByRole('button', { name: 'publicExperience.hidePassword' }))
    expect(password).toHaveAttribute('type', 'password')
    expect(mocks.login).not.toHaveBeenCalled()
  })

  it('announces missing credentials and focuses the first missing field', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><LoginPage /></MemoryRouter>)
    await user.click(await screen.findByRole('button', { name: 'common.signIn' }))
    expect(screen.getByRole('alert')).toHaveTextContent('common.pleaseEnterUsernameAndPassword')
    expect(screen.getByLabelText('auth.username')).toHaveFocus()
    expect(mocks.login).not.toHaveBeenCalled()
  })

  it('renders the login shell while public settings are still loading', async () => {
    mocks.getPublicSettings.mockReturnValue(new Promise(() => {}))

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('login-page-shell')).toBeInTheDocument()
  })

  it('keeps sign in disabled until Tencent captcha returns both ticket and randstr', async () => {
    mocks.getPublicSettings.mockResolvedValue({ captcha_provider: 'tencent', captcha_site_key: 'tencent-app-id' })
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    const signIn = await screen.findByRole('button', { name: 'common.signIn' })
    expect(signIn).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Incomplete Tencent Captcha' }))
    expect(signIn).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Complete Tencent Captcha' }))
    expect(signIn).toBeEnabled()
  })

  it('passes Tencent captcha ticket and randstr when signing in', async () => {
    mocks.getPublicSettings.mockResolvedValue({ captcha_provider: 'tencent', captcha_site_key: 'tencent-app-id' })
    mocks.login.mockResolvedValue(false)
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    await user.type(await screen.findByPlaceholderText('loginPage.enterUsername'), 'alice')
    await user.type(screen.getByPlaceholderText('loginPage.enterPassword'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Complete Tencent Captcha' }))
    await user.click(screen.getByRole('button', { name: 'common.signIn' }))

    expect(mocks.login).toHaveBeenCalledWith('alice', 'secret', undefined, 'ticket-123', 'rand-456')
  })
})
