import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import Layout from '@renderer/components/Layout'

vi.mock('@renderer/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: {
      nickname: 'Pathologist',
      email: 'path@example.com',
      role: 'pathologist',
      avatar_url: null,
    },
    logout: vi.fn(),
    needsAgreement: false,
    acceptAgreement: vi.fn(),
    isLoading: false,
    isAdmin: false,
    refreshUser: vi.fn(),
    maintenanceNoticeMessage: null,
    needsMaintenanceAcknowledgment: false,
    acknowledgeMaintenanceNotice: vi.fn(),
  }),
}))

vi.mock('@renderer/contexts/ToastContext', () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}))

vi.mock('@renderer/components/BackgroundTaskPanel', () => ({
  BackgroundTaskPanel: () => <div data-testid="background-task-panel" />,
}))

vi.mock('@renderer/components/InstallPWA', () => ({
  InstallPWA: () => null,
}))

vi.mock('@renderer/components/DisclaimerModal', () => ({
  DisclaimerModal: () => null,
}))

vi.mock('@renderer/components/PrivacyPolicyModal', () => ({
  PrivacyPolicyModal: () => null,
}))

vi.mock('@renderer/components/MaintenanceNoticeModal', () => ({
  MaintenanceNoticeModal: () => null,
}))

vi.mock('@renderer/components/ChangePasswordModal', () => ({
  ChangePasswordModal: () => null,
}))

vi.mock('@renderer/components/SetEmailModal', () => ({
  SetEmailModal: () => null,
}))

vi.mock('@renderer/components/common/LanguageSwitcher', () => ({
  LanguageSwitcher: () => <button type="button">Lang</button>,
}))

vi.mock('@renderer/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@renderer/api', () => ({
  uploadAvatar: vi.fn(),
  deleteAvatar: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

describe('Layout', () => {
  it('renders premium shell hooks around application chrome', () => {
    render(
      <MemoryRouter initialEntries={['/results']}>
        <Layout>
          <div>Results body</div>
        </Layout>
      </MemoryRouter>,
    )

    expect(screen.getByRole('banner')).toHaveAttribute('data-shell-header', 'true')
    expect(screen.getByRole('main')).toHaveAttribute('data-shell-main', 'true')
  })
})
