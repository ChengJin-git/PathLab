import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import LoginPage from '@renderer/pages/LoginPage'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  getPublicSettings: vi.fn(),
  getPublicMaintenanceNotice: vi.fn(),
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
vi.mock('@renderer/components/MaintenanceNoticeModal', () => ({ MaintenanceNoticeModal: () => null }))
vi.mock('@renderer/components/RegisterRequestModal', () => ({ RegisterRequestModal: () => null }))
vi.mock('@renderer/components/TencentCaptcha', () => ({
  TencentCaptcha: ({ onVerify }: { onVerify: (ticket: string, randstr: string) => void }) => (
    <div>
      <button type="button" onClick={() => onVerify('ticket-only', '')}>Incomplete Tencent Captcha</button>
      <button type="button" onClick={() => onVerify('ticket-123', 'rand-456')}>Complete Tencent Captcha</button>
    </div>
  ),
}))
vi.mock('@renderer/api', () => ({
  getPublicSettings: mocks.getPublicSettings,
  getPublicMaintenanceNotice: mocks.getPublicMaintenanceNotice,
  ApiError: class ApiError extends Error {},
}))

describe('LoginPage', () => {
  beforeEach(() => {
    mocks.login.mockReset()
    mocks.getPublicSettings.mockResolvedValue({ captcha_provider: null, captcha_site_key: '' })
    mocks.getPublicMaintenanceNotice.mockResolvedValue({ active: false, message: null })
  })

  it('renders the ambient blue-purple shell treatment', async () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    const shell = await screen.findByTestId('login-page-shell')
    expect(shell.className).toContain('from-[#eef3fb]')
    expect(shell.className).toContain('via-white')
    expect(shell.className).toContain('to-[#f6f3ff]')
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
