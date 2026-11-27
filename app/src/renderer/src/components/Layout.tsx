import React, { lazy, Suspense, useEffect, useState, useRef } from 'react'
import { Link, useLocation, useNavigate, Routes, Route } from 'react-router-dom'
import { LogOut, Camera, Trash2, Menu, KeyRound } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { Button } from './ui/button'
import { Tooltip } from './ui/tooltip'
import { InstallPWA } from './InstallPWA'
import { ChangePasswordModal } from './ChangePasswordModal'
import { uploadAvatar, deleteAvatar, ApiError } from '../api'
import { useTranslation } from 'react-i18next'
import { LanguageSwitcher } from './common/LanguageSwitcher'
import pathlabLogo from '../../public/images/pathlab-logo.png'
import { resolveAvatarUrl } from '../lib/avatarUrl'
import { getWorkspaceSelection, resetWorkspaceSelection, WORKSPACE_CHANGED } from '../lib/workspaceSelection'
import WorkbenchSidebar from './chat/WorkbenchSidebar'
import {useSidebarText} from './chat/sidebarText'
import PageLoading from './common/PageLoading'

import { loadChatPage, preloadDataPage } from '../lib/dataPages'

// The chat workspace mounts only once /dashboard is visited; keep it out of the startup chunk.
const AIChatPage = lazy(loadChatPage)

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout, needsAgreement, isAdmin, refreshUser } = useAuth()
  const { error: toastError, success: toastSuccess } = useToast()
  const { t } = useTranslation()
  const text=useSidebarText()
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const avatarSrc = resolveAvatarUrl(user?.avatar_url)
  const [workspaceSelection, setWorkspaceSelectionState] = useState(getWorkspaceSelection)
  React.useEffect(() => {
    const changed = () => setWorkspaceSelectionState(getWorkspaceSelection())
    window.addEventListener(WORKSPACE_CHANGED, changed)
    return () => window.removeEventListener(WORKSPACE_CHANGED, changed)
  }, [])

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
  useEffect(() => {
    // Chat is the home workspace: warm its chunk once the current page is idle.
    const warm = () => preloadDataPage('/dashboard')
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(warm, { timeout: 5000 })
      return () => window.cancelIdleCallback(id)
    }
    const id = window.setTimeout(warm, 2000)
    return () => window.clearTimeout(id)
  }, [])
  const isAutoResearchPage = location.pathname.startsWith('/autoresearch')
  const isUploadPage = location.pathname === '/upload'
  const isFullHeightPage = isAIChatPage || isAutoResearchPage || location.pathname === '/task-setup'
  const lastChatLocation = useRef<typeof location>();
  if(isAIChatPage)lastChatLocation.current=location;

  const handleLogout = async () => {
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
    <div className="flex h-dvh flex-col overflow-hidden text-[color:var(--surface-text)]">
      {/* Top Header */}
      <header data-shell-header="true" className="sticky top-0 z-50 flex-shrink-0 border-b border-[color:var(--surface-border)] bg-[color:var(--surface-work)]/94 backdrop-blur-xl pt-safe">
        <div className="w-full px-4 sm:px-5 lg:px-6">
          <div className="flex h-[4.25rem] items-center justify-between gap-4">
            {/* Logo Area */}
            <div className="flex min-w-0 items-center gap-2 sm:gap-3">
              {/* Mobile hamburger for AI Chat sidebar */}
              {(
                <button
                  type="button"
                  onClick={() => window.dispatchEvent(new CustomEvent('toggle-ai-sidebar'))}
                  className="rounded-full border border-transparent p-2 text-slate-500 transition-colors hover:border-[color:var(--surface-border)] hover:bg-white/80 hover:text-slate-950 lg:hidden"
                  aria-label={text('open')}
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
              {!isAIChatPage && workspaceSelection.workspaceId && <button type="button" className="rounded-full border px-3 py-1 text-xs text-gray-600" onClick={() => { resetWorkspaceSelection(); window.location.reload() }}>
                {t('aiChat.returnAllAreas')}
              </button>}
              {/* Background Tasks Notification Center */}
              <LanguageSwitcher variant="icon" />


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
                    aria-label={t('layout.profileMenu')}
                    aria-expanded={isMenuOpen}
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

                      <button type="button" onClick={handleLogout} className="flex min-h-10 w-full items-center gap-2 rounded-xl px-3 py-2 text-xs text-slate-700 transition-colors hover:bg-gray-50 hover:text-slate-950"><LogOut size={14}/>{t('auth.logout')}</button>
                    </div>
                  </div>
                )}
              </div>

            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex min-h-0 flex-1">
      <WorkbenchSidebar key={user?.id}/>
      <main
        data-shell-main="true"
        className="relative min-h-0 min-w-0 flex-1 overflow-hidden"
      >
        {lastChatLocation.current&&<div className={isAIChatPage?'h-full':'hidden'} aria-hidden={!isAIChatPage}><Suspense fallback={<PageLoading/>}><Routes location={lastChatLocation.current}><Route path="/dashboard/:conversationId?" element={<AIChatPage key={user?.id} visible={isAIChatPage}/>}/></Routes></Suspense></div>}
        {!isAIChatPage&&<div className={isFullHeightPage?'h-full overflow-hidden':'h-full overflow-y-auto'}>{isUploadPage ? (
          <div className="mx-auto w-full max-w-[var(--shell-max-width)] px-3 pb-6 pt-4 sm:px-5 sm:pb-8 lg:px-6 lg:pb-10">
            {children}
          </div>
        ) : (<div className={isFullHeightPage?'h-full':'mx-auto w-full max-w-[var(--shell-max-width)] px-3 py-4 sm:px-5 lg:px-6'}>{children}</div>)}</div>}
      </main>
      </div>
      <InstallPWA />

      <ChangePasswordModal
        isOpen={isChangePasswordOpen}
        onClose={() => setIsChangePasswordOpen(false)}
      />
    </div>
  )
}
