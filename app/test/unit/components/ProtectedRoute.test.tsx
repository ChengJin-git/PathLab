import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { ProtectedRoute } from '@renderer/components/ProtectedRoute'
import { useAuth } from '@renderer/contexts/AuthContext'
import i18n from '@renderer/i18n'

vi.mock('@renderer/contexts/AuthContext', () => ({ useAuth: vi.fn() }))
afterEach(cleanup)
it.each(['guest', 'pathologist'])('restricts settings for %s with a friendly message', async role => {
  await i18n.changeLanguage('en-US')
  vi.mocked(useAuth).mockReturnValue({ isLoading: false, isLoggedIn: true, isAdmin: false, isPathologist: role === 'pathologist' } as ReturnType<typeof useAuth>)
  render(<MemoryRouter><ProtectedRoute requireAdmin><div>Secret settings</div></ProtectedRoute></MemoryRouter>)
  expect(screen.getByRole('alert')).toHaveTextContent('contact your administrator')
  expect(screen.queryByText('Secret settings')).not.toBeInTheDocument()
})
it('blocks guest research even when GPU access is present', () => {
  vi.mocked(useAuth).mockReturnValue({ isLoading: false, isLoggedIn: true, isAdmin: false, isPathologist: false, canUseGpu: true } as ReturnType<typeof useAuth>)
  render(<MemoryRouter><ProtectedRoute requireResearch><div>Agent</div></ProtectedRoute></MemoryRouter>)
  expect(screen.queryByText('Agent')).not.toBeInTheDocument()
  expect(screen.getByRole('alert')).toBeInTheDocument()
})

it('presents terms before mounting protected content on any route', async () => {
  await i18n.changeLanguage('en-US')
  vi.mocked(useAuth).mockReturnValue({
    isLoading: false, isLoggedIn: true, isAdmin: false, isPathologist: true,
    needsAgreement: true, acceptAgreement: vi.fn(), logout: vi.fn(), error: null,
  } as unknown as ReturnType<typeof useAuth>)
  const mounted = vi.fn()
  function ProtectedContent() { mounted(); return <div>Slide data</div> }
  render(<MemoryRouter><ProtectedRoute><ProtectedContent /></ProtectedRoute></MemoryRouter>)
  expect(screen.getByRole('dialog', { name: 'Terms of Service & Medical Disclaimer' })).toBeInTheDocument()
  expect(mounted).not.toHaveBeenCalled()
  expect(screen.queryByText('Slide data')).not.toBeInTheDocument()
})
