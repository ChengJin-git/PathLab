import React, { useState, useRef } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LogOut, Settings, Camera, Trash2, Menu, KeyRound, Mail } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { Button } from './ui/button'
import { Tooltip } from './ui/tooltip'
import { BackgroundTaskPanel } from './BackgroundTaskPanel'
import { InstallPWA } from './InstallPWA'
import { DisclaimerModal } from './DisclaimerModal'
import { PrivacyPolicyModal } from './PrivacyPolicyModal'
import { MaintenanceNoticeModal } from './MaintenanceNoticeModal'
import { ChangePasswordModal } from './ChangePasswordModal'
import { SetEmailModal } from './SetEmailModal'
import { uploadAvatar, deleteAvatar, ApiError } from '../api'
import { useTranslation } from 'react-i18next'
import { LanguageSwitcher } from './common/LanguageSwitcher'
import pathlabLogo from '../../public/images/pathlab-logo.png'
import { resolveAvatarUrl } from '../lib/avatarUrl'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout, needsAgreement, acceptAgreement, isLoading, isAdmin, refreshUser, maintenanceNoticeMessage, needsMaintenanceAcknowledgment, acknowledgeMaintenanceNotice } = useAuth()
  const { error: toastError, success: toastSuccess } = useToast()
  const { t } = useTranslation()
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isPrivacyPolicyOpen, setIsPrivacyPolicyOpen] = useState(false)
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false)
  const [isSetEmailOpen, setIsSetEmailOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const avatarSrc = resolveAvatarUrl(user?.avatar_url)

  // Close menu when clicking outside
  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Check if current page is Dashboard (ChatGPT-style home page)
  const isAIChatPage = location.pathname.startsWith('/dashboard')
  const isAutoResearchPage = location.pathname.startsWith('/autoresearch')
  const isRegisterPage = location.pathname === '/register'
  const isFullHeightPage = isAIChatPage || isAutoResearchPage || location.pathname === '/task-setup'

  const handleLogout = async () => {
    await logout()
    navigate('/')
  }

  const handleAcceptAgreement = async () => {
    await acceptAgreement()
  }

  const handleDeclineAgreement = async () => {
    // If user declines, log them out
    await logout()
    navigate('/')
  }

  const handleAvatarClick = () => {
    setIsMenuOpen(!isMenuOpen)
  }

  const handleUploadClick = () => {
    fileInputRef.current?.click()
    setIsMenuOpen(false)
  }

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      try {
        await uploadAvatar(file)
        await refreshUser()
        toastSuccess(t('layout.avatarUploaded'))
      } catch (err) {
        console.error('Failed to upload avatar:', err)
        // Extract error message from ApiError or use generic message
        const errorMessage = err instanceof ApiError
          ? err.message
          : err instanceof Error
          ? err.message
          : 'Failed to upload avatar'
        toastError(errorMessage)
      }
    }
    // Clear input
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleDeleteAvatar = async () => {
    try {
      if (confirm(t('layout.deleteAvatarConfirm'))) {
        await deleteAvatar()
        await refreshUser()
        setIsMenuOpen(false)
        toastSuccess(t('layout.avatarDeleted'))
      }
    } catch (err) {
      console.error('Failed to delete avatar:', err)
      // Extract error message from ApiError or use generic message
      const errorMessage = err instanceof ApiError
        ? err.message
        : err instanceof Error
        ? err.message
        : t('layout.avatarUploadFailed')
      toastError(errorMessage)
    }
  }

  return (
    <div className={`flex flex-col text-[color:var(--surface-text)] ${isFullHeightPage
      ? 'h-screen overflow-hidden'
      : isRegisterPage
        ? 'h-screen' // Allow main to handle scroll
        : 'min-h-screen'}`}>
      {/* Top Header */}
      <header data-shell-header="true" className="sticky top-0 z-50 flex-shrink-0 border-b border-[color:var(--surface-border)] bg-[color:var(--surface-work)]/94 backdrop-blur-xl pt-safe">
        <div className="w-full px-4 sm:px-5 lg:px-6">
          <div className="flex h-[4.25rem] items-center justify-between gap-4">
            {/* Logo Area */}
            <div className="flex min-w-0 items-center gap-2 sm:gap-3">
              {/* Mobile hamburger for AI Chat sidebar */}
              {isAIChatPage && (
                <button
                  type="button"
                  onClick={() => window.dispatchEvent(new CustomEvent('toggle-ai-sidebar'))}
                  className="rounded-full border border-transparent p-2 text-slate-500 transition-colors hover:border-[color:var(--surface-border)] hover:bg-white/80 hover:text-slate-950 lg:hidden"
                  aria-label={t('aiChat.openChatHistory')}
                >
                  <Menu className="w-5 h-5" />
                </button>
              )}
              <Link to="/dashboard" className="flex flex-shrink-0 items-center transition-opacity hover:opacity-90">
                {/* Mobile: Show only the icon (crop the text) using overflow-hidden */}
                <div className="w-12 sm:w-auto overflow-hidden flex items-center justify-start">
                  <img
                    src={pathlabLogo}
                    alt="PathLab"
                    className="h-10 sm:h-10 max-w-none sm:max-w-full w-auto object-left"
                  />
                </div>
              </Link>
            </div>

            {/* Right Side Actions */}
            <div className="flex items-center gap-1.5 sm:gap-3">
              {/* Background Tasks Notification Center */}
              <BackgroundTaskPanel />

              {/* Settings Shortcut - Admin only */}
              {isAdmin && (
                <Tooltip content={t('common.settings')}>
                  <button
                    type="button"
                    onClick={() => navigate('/settings')}
                    className="rounded-full border border-transparent p-2 text-slate-500 transition-colors hover:border-primary-100 hover:bg-primary-50 hover:text-primary-700"
                  >
                    <Settings className="w-5 h-5" />
                  </button>
                </Tooltip>
              )}

              {/* Language Switcher */}
              <LanguageSwitcher variant="icon" />

              <div className="mx-1 hidden h-7 w-px bg-[color:var(--surface-border-strong)] sm:block sm:mx-2"></div>

              {/* User Profile */}
              <div className="relative flex items-center gap-2 sm:gap-3" ref={menuRef}>
                <div className="flex flex-col items-end hidden md:flex">
                  <span className="text-sm font-medium text-slate-900 leading-none">
                    {user?.nickname || user?.username || 'User'}
                  </span>
                  <span className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">{user?.role}</span>
                </div>

                <Tooltip content={t('layout.profileMenu')}>
                  <button
                    type="button"
                    onClick={handleAvatarClick}
                    className="group flex h-10 w-10 cursor-pointer items-center justify-center overflow-hidden rounded-full border border-white/70 bg-white shadow-[var(--shadow-soft)] transition-all hover:-translate-y-0.5 hover:border-primary-100"
                  >
                    {user?.avatar_url ? (
                      <img
                        src={avatarSrc ?? undefined}
                        alt="Avatar"
                        className="h-full w-full object-cover group-hover:opacity-90"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-primary-50 text-sm font-bold text-primary-700 transition-colors group-hover:bg-primary-100">
                        {(user?.nickname || user?.username || 'U').charAt(0).toUpperCase()}
                      </div>
                    )}
                  </button>
                </Tooltip>

                {/* Hidden file input */}
                <input
                  type="file"
                  ref={fileInputRef}
                  className="hidden"
                  accept="image/*"
                  onChange={handleFileChange}
                />

                {/* Dropdown Menu */}
                {isMenuOpen && (
                  <div className="absolute right-0 top-14 z-[60] w-auto min-w-[200px] max-w-[240px] overflow-hidden rounded-[1.4rem] border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] py-1.5 shadow-[var(--shadow-elevated)] backdrop-blur-xl">
                    <div className="border-b border-[color:var(--surface-border)] bg-[color:var(--surface-muted)]/70 px-4 py-3">
                      <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 opacity-80">{t('auth.signedInAs')}</p>
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-bold text-slate-900">
                            {user?.nickname || user?.username || 'User'}
                          </span>
                        </div>
                        <span className="mt-0.5 truncate text-[11px] leading-none text-slate-500 opacity-80">
                          {user?.email || (user?.nickname ? user?.username : '') || ''}
                        </span>
                      </div>
                    </div>

                    <div className="p-1.5">
                      <button
                        type="button"
                        onClick={handleUploadClick}
                        className="group flex w-full items-center rounded-xl px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-primary-50 hover:text-primary-700"
                      >
                        <Camera className="mr-2 h-3.5 w-3.5 text-slate-400 group-hover:text-primary-500" />
                        <span>{t('layout.uploadAvatar')}</span>
                      </button>

                      {user?.avatar_url && (
                        <button
                          type="button"
                          onClick={handleDeleteAvatar}
                          className="group flex w-full items-center rounded-xl px-3 py-2 text-xs font-medium text-red-600 transition-colors hover:bg-red-50"
                        >
                          <Trash2 className="mr-2 h-3.5 w-3.5 text-red-400 group-hover:text-red-500" />
                          <span>{t('layout.deleteAvatar')}</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => { setIsChangePasswordOpen(true); setIsMenuOpen(false) }}
                        className="group flex w-full items-center rounded-xl px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-primary-50 hover:text-primary-700"
                      >
                        <KeyRound className="mr-2 h-3.5 w-3.5 text-slate-400 group-hover:text-primary-500" />
                        <span>{t('layout.changePassword')}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => { setIsSetEmailOpen(true); setIsMenuOpen(false) }}
                        className="group flex w-full items-center rounded-xl px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-primary-50 hover:text-primary-700"
                      >
                        <Mail className="mr-2 h-3.5 w-3.5 text-slate-400 group-hover:text-primary-500" />
                        <span>{t('layout.setEmail')}</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Logout */}
              <Tooltip content={t('auth.logout')}>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleLogout}
                  className="text-slate-500 hover:text-red-600 hover:bg-red-50"
                >
                  <LogOut className="w-5 h-5" />
                </Button>
              </Tooltip>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main
        data-shell-main="true"
        className={`flex-1 ${isFullHeightPage
          ? 'h-full overflow-hidden'
          : isRegisterPage
            ? 'h-full w-full overflow-y-auto'
            : `mx-auto w-full max-w-[var(--shell-max-width)] px-3 pb-6 pt-4 sm:px-5 sm:pb-8 lg:px-6 lg:pb-10`
          }`}
      >
        {isRegisterPage ? (
          <div className="mx-auto w-full max-w-[var(--shell-max-width)] px-3 pb-6 pt-4 sm:px-5 sm:pb-8 lg:px-6 lg:pb-10">
            {children}
          </div>
        ) : (
          children
        )}
      </main>
      <InstallPWA />

      {/* Disclaimer Modal - shown when user needs to accept agreement */}
      <DisclaimerModal
        isOpen={needsAgreement}
        isLoading={isLoading}
        onAccept={handleAcceptAgreement}
        onDecline={handleDeclineAgreement}
        onOpenPrivacyPolicy={() => setIsPrivacyPolicyOpen(true)}
      />

      <PrivacyPolicyModal
        isOpen={needsAgreement && isPrivacyPolicyOpen}
        onClose={() => setIsPrivacyPolicyOpen(false)}
        onBackToTerms={() => setIsPrivacyPolicyOpen(false)}
      />

      <ChangePasswordModal
        isOpen={isChangePasswordOpen}
        onClose={() => setIsChangePasswordOpen(false)}
      />

      <SetEmailModal
        isOpen={isSetEmailOpen}
        onClose={() => setIsSetEmailOpen(false)}
      />

      {/* Maintenance Notice Modal - shown when admin posts a notice */}
      <MaintenanceNoticeModal
        isOpen={!needsAgreement && needsMaintenanceAcknowledgment}
        message={maintenanceNoticeMessage || ''}
        onAcknowledge={async () => { await acknowledgeMaintenanceNotice() }}
      />
    </div>
  )
}
