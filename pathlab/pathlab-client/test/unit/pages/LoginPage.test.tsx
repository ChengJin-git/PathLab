import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import LoginPage from '@renderer/pages/LoginPage'

vi.mock('@renderer/contexts/AuthContext', () => ({
  useAuth: () => ({
    login: vi.fn(),
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
vi.mock('@renderer/api', () => ({
  getPublicSettings: vi.fn().mockResolvedValue({ turnstile_site_key: null }),
  getPublicMaintenanceNotice: vi.fn().mockResolvedValue(null),
  ApiError: class ApiError extends Error {},
}))

describe('LoginPage', () => {
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
})
