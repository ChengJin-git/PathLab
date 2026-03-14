/**
 * Unit tests for AuthContext
 *
 * Tests authentication state management including:
 * - Initial load state
 * - Login / logout flows
 * - Role-based computed properties (isAdmin, isPathologist, canUseGpu, etc.)
 * - Agreement acceptance
 * - Maintenance notice acknowledgment
 * - Session expiry event handling
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

// ─── Mock @renderer/api ────────────────────────────────────────────────────

const mockGetCurrentUser = vi.fn()
const mockLoginWithCredentials = vi.fn()
const mockApiLogout = vi.fn()
const mockClearAuthToken = vi.fn()
const mockApiAcceptAgreement = vi.fn()
const mockGetMyDatasetPermissions = vi.fn()
const mockGetClientIP = vi.fn()
const mockGetMaintenanceNotice = vi.fn()
const mockApiAcknowledgeNotice = vi.fn()

vi.mock('@renderer/api', () => ({
  getCurrentUser: (...args: unknown[]) => mockGetCurrentUser(...args),
  loginWithCredentials: (...args: unknown[]) => mockLoginWithCredentials(...args),
  logout: (...args: unknown[]) => mockApiLogout(...args),
  clearAuthToken: (...args: unknown[]) => mockClearAuthToken(...args),
  acceptAgreement: (...args: unknown[]) => mockApiAcceptAgreement(...args),
  getMyDatasetPermissions: (...args: unknown[]) => mockGetMyDatasetPermissions(...args),
  getClientIP: (...args: unknown[]) => mockGetClientIP(...args),
  getMaintenanceNotice: (...args: unknown[]) => mockGetMaintenanceNotice(...args),
  acknowledgeNotice: (...args: unknown[]) => mockApiAcknowledgeNotice(...args),
  SESSION_EXPIRED_EVENT: 'pathlab:session-expired',
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status = 0) {
      super(message)
      this.name = 'ApiError'
      this.status = status
    }
    isNetworkError() { return this.status === 0 }
    isServerError() { return this.status >= 500 }
  },
}))

// ─── Mock ToastContext ──────────────────────────────────────────────────────

const mockToastWarning = vi.fn()
const mockToastSuccess = vi.fn()
const mockToastError = vi.fn()
const mockToastInfo = vi.fn()

vi.mock('@renderer/contexts/ToastContext', () => ({
  useToast: () => ({
    warning: mockToastWarning,
    success: mockToastSuccess,
    error: mockToastError,
    info: mockToastInfo,
    toast: vi.fn(),
    toasts: [],
    removeToast: vi.fn(),
  }),
}))

// ─── Mock react-i18next ────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { t: (key: string) => key, language: 'en-US' },
  }),
}))

// ─── Import after mocks ────────────────────────────────────────────────────

import { AuthProvider, useAuth, BEFORE_LOGOUT_EVENT } from '@renderer/contexts/AuthContext'

// ─── Helpers ───────────────────────────────────────────────────────────────

function buildUser(overrides: Record<string, unknown> = {}) {
  return {
    id: '1',
    username: 'alice',
    email: 'alice@lab.io',
    role: 'pathologist',
    is_active: true,
    agreement_accepted_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}

function notLoggedIn() {
  mockGetCurrentUser.mockResolvedValue({ is_logged_in: false, user: null })
  mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })
  mockGetMaintenanceNotice.mockResolvedValue({ active: false, message: null, needs_acknowledgment: false })
}

function loggedInAs(userOverrides: Record<string, unknown> = {}) {
  const user = buildUser(userOverrides)
  mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user })
  mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })
  mockGetMaintenanceNotice.mockResolvedValue({ active: false, message: null, needs_acknowledgment: false })
  return user
}

// ─── Tests ─────────────────────────────────────────────────────────────────

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── Initial state ──────────────────────────────────────────────────────

  describe('initial state', () => {
    it('starts with isLoading=true and user=null', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })

      // Immediately after render, isLoading should be true
      expect(result.current.isLoading).toBe(true)
      expect(result.current.user).toBe(null)

      // After mount effect resolves
      await waitFor(() => expect(result.current.isLoading).toBe(false))
      expect(result.current.user).toBe(null)
      expect(result.current.isLoggedIn).toBe(false)
    })

    it('sets user when getCurrentUser returns logged-in user', async () => {
      const user = loggedInAs({ role: 'pathologist', agreement_accepted_at: '2024-01-01T00:00:00Z' })
      const { result } = renderHook(() => useAuth(), { wrapper })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.user).toMatchObject({ id: user.id, username: user.username })
      expect(result.current.isLoggedIn).toBe(true)
    })

    it('sets error when getCurrentUser throws', async () => {
      mockGetCurrentUser.mockRejectedValue(new Error('network failure'))
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })

      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.user).toBe(null)
      expect(result.current.error).toBe('network failure')
    })
  })

  // ── login() ────────────────────────────────────────────────────────────

  describe('login()', () => {
    it('returns true and sets user on success', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      // Now mock as logged in for the refresh after login
      const user = buildUser()
      mockLoginWithCredentials.mockResolvedValue(undefined)
      mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user })
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })

      let loginResult: boolean
      await act(async () => {
        loginResult = await result.current.login('alice', 'secret')
      })

      expect(loginResult!).toBe(true)
      await waitFor(() => expect(result.current.user).toMatchObject({ username: 'alice' }))
    })

    it('passes turnstileToken to loginWithCredentials', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockLoginWithCredentials.mockResolvedValue(undefined)
      mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user: buildUser() })
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })

      await act(async () => {
        await result.current.login('alice', 'secret', 'turnstile_token_123')
      })

      expect(mockLoginWithCredentials).toHaveBeenCalledWith('alice', 'secret', 'turnstile_token_123')
    })

    it('returns false and sets error on bad credentials', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockLoginWithCredentials.mockRejectedValue(new Error('login_bad_credentials'))

      let loginResult: boolean
      await act(async () => {
        loginResult = await result.current.login('alice', 'wrong')
      })

      expect(loginResult!).toBe(false)
      expect(result.current.error).toBe('Invalid username or password')
    })

    it('returns false with maintenance message on maintenance_mode error', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockLoginWithCredentials.mockRejectedValue(new Error('maintenance_mode'))

      let loginResult: boolean
      await act(async () => {
        loginResult = await result.current.login('alice', 'secret')
      })

      expect(loginResult!).toBe(false)
      expect(result.current.error).toContain('maintenance')
    })

    it('returns false with deactivated message on login_user_not_active error', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockLoginWithCredentials.mockRejectedValue(new Error('login_user_not_active'))

      let loginResult: boolean
      await act(async () => {
        loginResult = await result.current.login('alice', 'secret')
      })

      expect(loginResult!).toBe(false)
      expect(result.current.error).toContain('deactivated')
    })

    it('clears error via clearError()', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockLoginWithCredentials.mockRejectedValue(new Error('login_bad_credentials'))
      await act(async () => { await result.current.login('alice', 'wrong') })
      expect(result.current.error).not.toBe(null)

      act(() => { result.current.clearError() })
      expect(result.current.error).toBe(null)
    })
  })

  // ── logout() ───────────────────────────────────────────────────────────

  describe('logout()', () => {
    it('dispatches BEFORE_LOGOUT_EVENT and clears user', async () => {
      loggedInAs()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.user).not.toBe(null))

      const events: string[] = []
      window.addEventListener(BEFORE_LOGOUT_EVENT, () => events.push(BEFORE_LOGOUT_EVENT))

      mockApiLogout.mockResolvedValue(undefined)

      await act(async () => { await result.current.logout() })

      expect(events).toContain(BEFORE_LOGOUT_EVENT)
      expect(result.current.user).toBe(null)
      expect(result.current.isLoggedIn).toBe(false)
    })

    it('clears user even when apiLogout throws', async () => {
      loggedInAs()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.user).not.toBe(null))

      mockApiLogout.mockRejectedValue(new Error('network error'))

      await act(async () => { await result.current.logout() })

      expect(result.current.user).toBe(null)
      expect(mockClearAuthToken).toHaveBeenCalled()
    })
  })

  // ── Role checks ────────────────────────────────────────────────────────

  describe('role checks', () => {
    it('isAdmin=true for admin role', async () => {
      loggedInAs({ role: 'admin' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.isAdmin).toBe(true)
      expect(result.current.isPathologist).toBe(false)
    })

    it('isPathologist=true for pathologist role', async () => {
      loggedInAs({ role: 'pathologist' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.isPathologist).toBe(true)
      expect(result.current.isAdmin).toBe(false)
    })

    it('canUseGpu=true for admin', async () => {
      loggedInAs({ role: 'admin' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.canUseGpu).toBe(true)
    })

    it('canUseGpu=true for pathologist', async () => {
      loggedInAs({ role: 'pathologist' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.canUseGpu).toBe(true)
    })

    it('canUseGpu=false for guest role', async () => {
      loggedInAs({ role: 'guest' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.canUseGpu).toBe(false)
    })

    it('isAdmin=false, isPathologist=false, canUseGpu=false when not logged in', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.isAdmin).toBe(false)
      expect(result.current.isPathologist).toBe(false)
      expect(result.current.canUseGpu).toBe(false)
    })
  })

  // ── canUseGpuForDataset() ──────────────────────────────────────────────

  describe('canUseGpuForDataset()', () => {
    it('returns true for admin regardless of dataset', async () => {
      loggedInAs({ role: 'admin' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.canUseGpuForDataset('any-dataset-id')).toBe(true)
    })

    it('returns false for guest with no elevated access', async () => {
      loggedInAs({ role: 'guest' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.canUseGpuForDataset('ds-123')).toBe(false)
    })

    it('returns true for guest with elevated access to that dataset', async () => {
      const user = buildUser({ role: 'guest' })
      mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user })
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: ['ds-456'] })
      mockGetMaintenanceNotice.mockResolvedValue({ active: false, message: null, needs_acknowledgment: false })

      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.canUseGpuForDataset('ds-456')).toBe(true)
      expect(result.current.canUseGpuForDataset('ds-999')).toBe(false)
    })
  })

  // ── needsAgreement ─────────────────────────────────────────────────────

  describe('needsAgreement', () => {
    it('false when user is not logged in', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.needsAgreement).toBe(false)
    })

    it('false for admin even without agreement_accepted_at', async () => {
      loggedInAs({ role: 'admin', agreement_accepted_at: null })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.needsAgreement).toBe(false)
    })

    it('true for pathologist without agreement_accepted_at', async () => {
      loggedInAs({ role: 'pathologist', agreement_accepted_at: null })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.needsAgreement).toBe(true)
    })

    it('true for guest without agreement_accepted_at', async () => {
      loggedInAs({ role: 'guest', agreement_accepted_at: null })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.needsAgreement).toBe(true)
    })

    it('false for pathologist who already accepted', async () => {
      loggedInAs({ role: 'pathologist', agreement_accepted_at: '2024-06-01T00:00:00Z' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.needsAgreement).toBe(false)
    })
  })

  // ── acceptAgreement() ──────────────────────────────────────────────────

  describe('acceptAgreement()', () => {
    it('returns true and updates user on success', async () => {
      loggedInAs({ role: 'pathologist', agreement_accepted_at: null })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      const updatedUser = buildUser({ role: 'pathologist', agreement_accepted_at: '2024-07-01T00:00:00Z' })
      mockGetClientIP.mockResolvedValue('10.0.0.1')
      mockApiAcceptAgreement.mockResolvedValue(updatedUser)

      let accepted: boolean
      await act(async () => {
        accepted = await result.current.acceptAgreement()
      })

      expect(accepted!).toBe(true)
      expect(mockGetClientIP).toHaveBeenCalled()
      expect(mockApiAcceptAgreement).toHaveBeenCalledWith('10.0.0.1')
      expect(result.current.user?.agreement_accepted_at).toBe('2024-07-01T00:00:00Z')
    })

    it('passes undefined IP when getClientIP returns null', async () => {
      loggedInAs({ role: 'pathologist', agreement_accepted_at: null })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockGetClientIP.mockResolvedValue(null)
      mockApiAcceptAgreement.mockResolvedValue(buildUser({ agreement_accepted_at: '2024-07-01T00:00:00Z' }))

      await act(async () => { await result.current.acceptAgreement() })

      expect(mockApiAcceptAgreement).toHaveBeenCalledWith(undefined)
    })

    it('returns false and sets error on failure', async () => {
      loggedInAs({ role: 'pathologist', agreement_accepted_at: null })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockGetClientIP.mockResolvedValue('10.0.0.1')
      mockApiAcceptAgreement.mockRejectedValue(new Error('server error'))

      let accepted: boolean
      await act(async () => {
        accepted = await result.current.acceptAgreement()
      })

      expect(accepted!).toBe(false)
      expect(result.current.error).toBe('server error')
    })
  })

  // ── Maintenance notice ─────────────────────────────────────────────────

  describe('maintenance notice', () => {
    it('sets maintenanceNoticeMessage when notice is active', async () => {
      const user = buildUser({ role: 'pathologist' })
      mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user })
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })
      mockGetMaintenanceNotice.mockResolvedValue({
        active: true,
        message: 'Server maintenance tonight',
        needs_acknowledgment: true,
      })

      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))
      await waitFor(() => expect(result.current.maintenanceNoticeMessage).toBe('Server maintenance tonight'))

      expect(result.current.needsMaintenanceAcknowledgment).toBe(true)
    })

    it('clears maintenanceNoticeMessage when notice is not active', async () => {
      loggedInAs()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.maintenanceNoticeMessage).toBe(null)
      expect(result.current.needsMaintenanceAcknowledgment).toBe(false)
    })

    it('clears notice state when user logs out', async () => {
      const user = buildUser({ role: 'pathologist' })
      mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user })
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })
      mockGetMaintenanceNotice.mockResolvedValue({
        active: true,
        message: 'Maintenance',
        needs_acknowledgment: true,
      })

      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.maintenanceNoticeMessage).toBe('Maintenance'))

      mockApiLogout.mockResolvedValue(undefined)
      await act(async () => { await result.current.logout() })

      expect(result.current.maintenanceNoticeMessage).toBe(null)
      expect(result.current.needsMaintenanceAcknowledgment).toBe(false)
    })
  })

  // ── acknowledgeMaintenanceNotice() ─────────────────────────────────────

  describe('acknowledgeMaintenanceNotice()', () => {
    it('returns true, updates user, and clears acknowledgment flag', async () => {
      const user = buildUser({ role: 'pathologist' })
      mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user })
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: [] })
      mockGetMaintenanceNotice
        .mockResolvedValueOnce({ active: true, message: 'Maintenance', needs_acknowledgment: true })
        .mockResolvedValue({ active: false, message: null, needs_acknowledgment: false })

      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.needsMaintenanceAcknowledgment).toBe(true))

      const updatedUser = buildUser()
      mockApiAcknowledgeNotice.mockResolvedValue(updatedUser)

      let acked: boolean
      await act(async () => {
        acked = await result.current.acknowledgeMaintenanceNotice()
      })

      expect(acked!).toBe(true)
      expect(result.current.needsMaintenanceAcknowledgment).toBe(false)
      expect(result.current.user).toMatchObject({ id: updatedUser.id })
    })

    it('returns false on failure', async () => {
      loggedInAs()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      mockApiAcknowledgeNotice.mockRejectedValue(new Error('ack failed'))

      let acked: boolean
      await act(async () => {
        acked = await result.current.acknowledgeMaintenanceNotice()
      })

      expect(acked!).toBe(false)
    })
  })

  // ── SESSION_EXPIRED_EVENT ──────────────────────────────────────────────

  describe('SESSION_EXPIRED_EVENT', () => {
    it('clears user and shows toast warning when session expires while logged in', async () => {
      loggedInAs()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.user).not.toBe(null))

      act(() => {
        window.dispatchEvent(new CustomEvent('pathlab:session-expired'))
      })

      await waitFor(() => expect(result.current.user).toBe(null))
      expect(mockToastWarning).toHaveBeenCalled()
    })

    it('does not show toast when user is already null (not logged in)', async () => {
      notLoggedIn()
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      act(() => {
        window.dispatchEvent(new CustomEvent('pathlab:session-expired'))
      })

      // Give React a moment to process
      await new Promise(resolve => setTimeout(resolve, 50))
      expect(mockToastWarning).not.toHaveBeenCalled()
    })
  })

  // ── useAuth outside provider ───────────────────────────────────────────

  describe('useAuth outside provider', () => {
    it('throws when used outside AuthProvider', () => {
      // Suppress React error output for this test
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      expect(() => renderHook(() => useAuth())).toThrow(
        'useAuth must be used within an AuthProvider'
      )
      consoleSpy.mockRestore()
    })
  })

  // ── refreshDatasetPermissions() ────────────────────────────────────────

  describe('refreshDatasetPermissions()', () => {
    it('updates elevatedDatasetIds on success', async () => {
      loggedInAs({ role: 'guest' })
      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      // Initially empty
      expect(result.current.elevatedDatasetIds).toEqual([])

      // Now elevated access is granted
      mockGetMyDatasetPermissions.mockResolvedValue({ elevated_dataset_ids: ['ds-777'] })
      await act(async () => { await result.current.refreshDatasetPermissions() })

      expect(result.current.elevatedDatasetIds).toEqual(['ds-777'])
      expect(result.current.canUseGpuForDataset('ds-777')).toBe(true)
    })

    it('resets elevatedDatasetIds to [] on failure', async () => {
      const user = buildUser({ role: 'guest' })
      mockGetCurrentUser.mockResolvedValue({ is_logged_in: true, user })
      mockGetMyDatasetPermissions
        .mockResolvedValueOnce({ elevated_dataset_ids: ['ds-777'] })
        .mockRejectedValueOnce(new Error('server error'))
      mockGetMaintenanceNotice.mockResolvedValue({ active: false, message: null, needs_acknowledgment: false })

      const { result } = renderHook(() => useAuth(), { wrapper })
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      // After initial load (first mockResolvedValue), elevated_dataset_ids should be ['ds-777']
      expect(result.current.elevatedDatasetIds).toEqual(['ds-777'])

      // Now refresh fails
      await act(async () => { await result.current.refreshDatasetPermissions() })
      expect(result.current.elevatedDatasetIds).toEqual([])
    })
  })
})
