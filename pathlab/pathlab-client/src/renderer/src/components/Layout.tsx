import React, { useState, useRef } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LogOut, Settings, Camera, Trash2, User as UserIcon, Menu, KeyRound, Mail } from 'lucide-react'
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
  const isRegisterPage = location.pathname === '/register'

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
    <div className={`bg-gray-50 flex flex-col ${isAIChatPage || location.pathname === '/task-setup'
      ? 'h-screen overflow-hidden'
      : isRegisterPage
        ? 'h-screen' // Allow main to handle scroll
        : 'min-h-screen'}`}>
      {/* Top Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-200/50 sticky top-0 z-50 shadow-sm flex-shrink-0 pt-safe">
        <div className="w-full mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            {/* Logo Area */}
            <div className="flex items-center">
              {/* Mobile hamburger for AI Chat sidebar */}
              {isAIChatPage && (
                <button
                  type="button"
                  onClick={() => window.dispatchEvent(new CustomEvent('toggle-ai-sidebar'))}
                  className="p-2 mr-1 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-full transition-colors lg:hidden"
                  aria-label={t('aiChat.openChatHistory')}
                >
                  <Menu className="w-5 h-5" />
                </button>
              )}
              <Link to="/dashboard" className="flex-shrink-0 flex items-center hover:opacity-80 transition-opacity">
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
            <div className="flex items-center space-x-1.5 sm:space-x-4">
              {/* Background Tasks Notification Center */}
              <BackgroundTaskPanel />

              {/* Settings Shortcut - Admin only */}
              {isAdmin && (
                <Tooltip content={t('common.settings')}>
                  <button
                    type="button"
                    onClick={() => navigate('/settings')}
                    className="p-1.5 sm:p-2 text-gray-500 hover:text-primary-600 hover:bg-gray-100 rounded-lg transition-colors"
                  >
                    <Settings className="w-5 h-5" />
                  </button>
                </Tooltip>
              )}

              {/* Language Switcher */}
              <LanguageSwitcher variant="icon" />

              <div className="hidden sm:block h-6 w-px bg-gray-200 mx-1 sm:mx-2"></div>

              {/* User Profile */}
              <div className="flex items-center space-x-2 sm:space-x-3 relative" ref={menuRef}>
                <div className="flex flex-col items-end hidden md:flex">
                  <span className="text-sm font-medium text-gray-900 leading-none">
                    {user?.nickname || user?.email?.split('@')[0] || 'User'}
                  </span>
                  <span className="text-[10px] text-gray-400 mt-1 uppercase tracking-wider font-semibold">{user?.role}</span>
                </div>

                <Tooltip content={t('layout.profileMenu')}>
                  <button
                    type="button"
                    onClick={handleAvatarClick}
                    className="w-9 h-9 rounded-full overflow-hidden flex items-center justify-center ring-2 ring-white shadow-sm hover:ring-primary-100 transition-all cursor-pointer group"
                  >
                    {user?.avatar_url ? (
                      <img
                        src={avatarSrc ?? undefined}
                        alt="Avatar"
                        className="w-full h-full object-cover group-hover:opacity-90"
                      />
                    ) : (
                      <div className="w-full h-full bg-primary-100 flex items-center justify-center text-sm font-bold text-primary-700 group-hover:bg-primary-200 transition-colors">
                        {(user?.nickname || user?.email?.split('@')[0] || 'U').charAt(0).toUpperCase()}
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
                  <div className="absolute right-0 top-12 w-auto min-w-[140px] max-w-[200px] bg-white rounded-xl shadow-xl border border-gray-100 py-1 z-[60] overflow-hidden">
                    <div className="px-3 py-2 border-b border-gray-50 bg-gray-50/30">
                      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1 opacity-70">{t('auth.signedInAs')}</p>
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold text-gray-900 truncate">
                            {user?.nickname || 'User'}
                          </span>
                        </div>
                        <span className="text-[11px] text-gray-500 truncate opacity-80 leading-none mt-0.5">
                          {user?.email || ''}
                        </span>
                      </div>
                    </div>

                    <div className="p-0.5">
                      <button
                        type="button"
                        onClick={handleUploadClick}
                        className="w-full flex items-center px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-primary-50 hover:text-primary-700 rounded-lg transition-colors group"
                      >
                        <Camera className="w-3.5 h-3.5 mr-2 text-gray-400 group-hover:text-primary-500" />
                        <span>{t('layout.uploadAvatar')}</span>
                      </button>

                      {user?.avatar_url && (
                        <button
                          type="button"
                          onClick={handleDeleteAvatar}
                          className="w-full flex items-center px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 rounded-lg transition-colors group"
                        >
                          <Trash2 className="w-3.5 h-3.5 mr-2 text-red-400 group-hover:text-red-500" />
                          <span>{t('layout.deleteAvatar')}</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => { setIsChangePasswordOpen(true); setIsMenuOpen(false) }}
                        className="w-full flex items-center px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-primary-50 hover:text-primary-700 rounded-lg transition-colors group"
                      >
                        <KeyRound className="w-3.5 h-3.5 mr-2 text-gray-400 group-hover:text-primary-500" />
                        <span>{t('layout.changePassword')}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => { setIsSetEmailOpen(true); setIsMenuOpen(false) }}
                        className="w-full flex items-center px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-primary-50 hover:text-primary-700 rounded-lg transition-colors group"
                      >
                        <Mail className="w-3.5 h-3.5 mr-2 text-gray-400 group-hover:text-primary-500" />
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
                  className="text-gray-500 hover:text-red-600 hover:bg-red-50"
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
        className={`flex-1 ${isAIChatPage || location.pathname === '/task-setup'
          ? 'h-full overflow-hidden'
          : isRegisterPage
            ? 'w-full mx-auto p-3 sm:p-6 lg:p-8 h-full overflow-y-auto'
            : `w-full mx-auto p-3 sm:p-6 lg:p-8`
          }`}
      >
        {children}
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
