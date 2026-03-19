/**
 * PathLab Login Page
 *
 * Landing page with username/password login.
 * Registration is only available through admin in Settings.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { Microscope, Brain, Shield, Zap, LogIn, Loader2, User, Lock, Heart, ExternalLink, AlertTriangle, UserPlus } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { DisclaimerModal } from '../components/DisclaimerModal'
import { PrivacyPolicyModal } from '../components/PrivacyPolicyModal'
import { getPublicSettings, getPublicMaintenanceNotice, ApiError } from '../api'
import { MaintenanceNoticeModal } from '../components/MaintenanceNoticeModal'
import { RegisterRequestModal } from '../components/RegisterRequestModal'

/**
 * Inner login page component.
 * When turnstileSiteKey is provided, renders a Cloudflare Turnstile widget.
 */
function LoginPageInner({ backendUnavailable = false, turnstileSiteKey }: { backendUnavailable?: boolean; turnstileSiteKey?: string }) {
  const navigate = useNavigate()
  const { login, isLoading, error, isLoggedIn } = useAuth()
  const { t } = useTranslation()

  // Form state
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [formError, setFormError] = React.useState<string | null>(null)
  const [isRegisterOpen, setIsRegisterOpen] = React.useState(false)
  const [isTermsPreviewOpen, setIsTermsPreviewOpen] = React.useState(false)
  const [isPrivacyPreviewOpen, setIsPrivacyPreviewOpen] = React.useState(false)

  // Turnstile state
  const [turnstileToken, setTurnstileToken] = React.useState<string | undefined>(undefined)
  const turnstileRef = React.useRef<HTMLDivElement>(null)
  const turnstileWidgetId = React.useRef<string | null>(null)

  // If already logged in, redirect to dashboard
  React.useEffect(() => {
    if (isLoggedIn) {
      navigate('/dashboard')
    }
  }, [isLoggedIn, navigate])

  // Load and render Cloudflare Turnstile widget
  React.useEffect(() => {
    if (!turnstileSiteKey || !turnstileRef.current) return

    const renderWidget = () => {
      if (!turnstileRef.current || turnstileWidgetId.current !== null) return
      const widgetId = (window as any).turnstile.render(turnstileRef.current, {
        sitekey: turnstileSiteKey,
        callback: (token: string) => setTurnstileToken(token),
        'expired-callback': () => setTurnstileToken(undefined),
        'error-callback': () => setTurnstileToken(undefined),
        theme: 'light',
        size: 'flexible',
      })
      turnstileWidgetId.current = widgetId
    }

    // If Turnstile script is already loaded
    if ((window as any).turnstile) {
      renderWidget()
      return
    }

    // Load Turnstile script
    const script = document.createElement('script')
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
    script.async = true
    script.onload = renderWidget
    document.head.appendChild(script)

    return () => {
      // Cleanup widget on unmount
      if (turnstileWidgetId.current !== null && (window as any).turnstile) {
        try {
          (window as any).turnstile.remove(turnstileWidgetId.current)
        } catch { /* ignore */ }
        turnstileWidgetId.current = null
      }
    }
  }, [turnstileSiteKey])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    if (!username || !password) {
      setFormError(t('common.pleaseEnterUsernameAndPassword'))
      return
    }

    const success = await login(username, password, turnstileToken)
    if (success) {
      navigate('/dashboard')
    } else {
      // Reset Turnstile widget after failed login (token is single-use)
      if (turnstileWidgetId.current !== null && (window as any).turnstile) {
        try {
          (window as any).turnstile.reset(turnstileWidgetId.current)
          setTurnstileToken(undefined)
        } catch { /* ignore */ }
      }
    }
  }

  const features = [
    {
      icon: Microscope,
      title: t('loginPage.features.wsiVisualization'),
      description: t('loginPage.features.wsiVisualizationDesc'),
    },
    {
      icon: Brain,
      title: t('loginPage.features.aiAnalysis'),
      description: t('loginPage.features.aiAnalysisDesc'),
    },
    {
      icon: Shield,
      title: t('loginPage.features.privacyFirst'),
      description: t('loginPage.features.privacyFirstDesc'),
    },
    {
      icon: Zap,
      title: t('loginPage.features.smartAssistant'),
      description: t('loginPage.features.smartAssistantDesc'),
    },
  ]

  return (
    <div className="h-screen flex flex-col lg:flex-row bg-slate-50 overflow-hidden relative">

      {/* Language Switcher */}
      <div className="absolute top-3 right-3 z-50">
        <LanguageSwitcher />
      </div>

      {/* Left: Login Section */}
      <div className="flex-1 flex flex-col justify-center px-6 py-12 lg:px-12 relative bg-white lg:max-w-[480px] xl:max-w-[560px] border-r border-slate-100 z-10 shadow-xl overflow-hidden">
        {/* Background Decoration */}
        <div className="absolute top-0 left-0 w-full h-2 bg-gradient-to-r from-blue-600 to-cyan-500" />
        <div className="absolute -top-24 -left-24 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl opacity-50" />
        <div className="absolute -bottom-24 -right-24 w-64 h-64 bg-cyan-500/5 rounded-full blur-3xl opacity-50" />

        <div className="w-full max-w-sm mx-auto z-10">
          <div className="mb-10 text-center lg:text-left">
            <div className="flex items-center justify-center lg:justify-start mb-6">
              <img
                src="/images/pathlab-logo.png"
                alt="PathLab"
                className="h-12 w-auto"
              />
            </div>
            <h2 className="text-3xl font-bold text-slate-900 mb-2">{t('auth.welcomeBack')}</h2>
          </div>

          <form onSubmit={handleLogin} className="space-y-6">
            <div className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-500 ml-1">{t('auth.username')}</label>
                <div className="relative group">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                  <Input
                    id="username"
                    type="text"
                    placeholder={t('loginPage.enterUsername')}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="pl-10 h-11 bg-slate-50 border-slate-200 focus:bg-white focus:ring-2 focus:ring-blue-100 focus:border-blue-500 rounded-lg transition-all"
                    disabled={isLoading}
                    autoComplete="username"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex items-center justify-between ml-1">
                  <label className="text-xs font-semibold text-slate-500">{t('auth.password')}</label>
                </div>
                <div className="relative group">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                  <Input
                    id="password"
                    type="password"
                    placeholder={t('loginPage.enterPassword')}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10 h-11 bg-slate-50 border-slate-200 focus:bg-white focus:ring-2 focus:ring-blue-100 focus:border-blue-500 rounded-lg transition-all"
                    disabled={isLoading}
                    autoComplete="current-password"
                  />
                </div>
              </div>
            </div>

            {/* Backend Unavailable / Maintenance Banner */}
            {backendUnavailable && (
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-sm font-medium flex items-start gap-2 animate-in fade-in slide-in-from-top-2">
                <AlertTriangle className="w-4 h-4 mt-0.5 text-amber-500 flex-shrink-0" />
                <p>{t('auth.systemMaintenance')}</p>
              </div>
            )}

            {/* Error Message */}
            {(error || formError) && (
              <div className="p-3 bg-red-50 border border-red-100 rounded-lg text-red-600 text-sm font-medium flex items-start gap-2 animate-in fade-in slide-in-from-top-2">
                <div className="w-1 h-4 mt-0.5 rounded-full bg-red-500 flex-shrink-0" />
                <p>{formError || error}</p>
              </div>
            )}

            {/* Cloudflare Turnstile Widget */}
            {turnstileSiteKey && (
              <div ref={turnstileRef} className="flex justify-center" />
            )}

            <Button
              type="submit"
              disabled={isLoading || (!!turnstileSiteKey && !turnstileToken)}
              className="w-full h-11 bg-slate-900 hover:bg-slate-800 text-white font-medium rounded-lg shadow-lg hover:shadow-xl transition-all flex items-center justify-center gap-2"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
              {t('common.signIn')}
            </Button>

            <Button
              type="button"
              variant="outline"
              onClick={() => setIsRegisterOpen(true)}
              className="w-full h-11 border-slate-200 text-slate-700 hover:bg-slate-50 font-medium rounded-lg flex items-center justify-center gap-2"
            >
              <UserPlus className="w-4 h-4" />
              {t('loginPage.requestAccess')}
            </Button>

            <div className="rounded-2xl bg-slate-50/80 px-5 py-4 shadow-[0_10px_30px_rgba(15,23,42,0.06)]">
              <div className="mx-auto max-w-sm text-center">
                <p className="text-xs leading-relaxed text-slate-500">
                  {t('loginPage.legalNotice')}
                </p>

                <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setIsTermsPreviewOpen(true)}
                    className="group h-auto justify-center rounded-full bg-white/85 px-4 py-2 text-xs font-semibold text-slate-700 shadow-[0_4px_14px_rgba(15,23,42,0.08)] transition-all hover:-translate-y-0.5 hover:bg-white hover:shadow-[0_8px_20px_rgba(15,23,42,0.12)]"
                  >
                    <Shield className="mr-1.5 h-3.5 w-3.5 text-blue-600" />
                    <span>{t('loginPage.viewTerms')}</span>
                    <ExternalLink className="ml-1.5 h-3 w-3 text-slate-400 transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                  </Button>

                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setIsPrivacyPreviewOpen(true)}
                    className="group h-auto justify-center rounded-full bg-white/85 px-4 py-2 text-xs font-semibold text-slate-700 shadow-[0_4px_14px_rgba(15,23,42,0.08)] transition-all hover:-translate-y-0.5 hover:bg-white hover:shadow-[0_8px_20px_rgba(15,23,42,0.12)]"
                  >
                    <Lock className="mr-1.5 h-3.5 w-3.5 text-emerald-600" />
                    <span>{t('loginPage.viewPrivacy')}</span>
                    <ExternalLink className="ml-1.5 h-3 w-3 text-slate-400 transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                  </Button>
                </div>
              </div>
            </div>

            <p className="text-center text-xs text-slate-400 mt-6">
              © 2026 <a href="https://smartlab.cse.ust.hk/" target="_blank" rel="noopener noreferrer">SmartLab</a>{turnstileSiteKey ? ` · ${t('common.protectedByTurnstile')}` : ''}
            </p>
          </form>
        </div>
      </div>

      {/* Right: Features & Donation Section */}
      <div className="hidden lg:flex flex-1 relative bg-slate-50 overflow-hidden flex-col justify-between p-12 xl:p-16 border-l border-slate-200">

        {/* Abstract Background */}
        <div className="absolute top-0 right-0 w-full h-full bg-white opacity-40">
          <div className="absolute right-0 top-0 w-96 h-96 bg-blue-100 rounded-full blur-3xl opacity-60 translate-x-1/3 -translate-y-1/3"></div>
          <div className="absolute left-0 bottom-0 w-96 h-96 bg-cyan-100 rounded-full blur-3xl opacity-60 -translate-x-1/3 translate-y-1/3"></div>
        </div>

        {/* Content */}
        <div className="relative z-10 max-w-2xl mx-auto h-full flex flex-col justify-center">

          <div className="mb-12">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-blue-600 text-white shadow-lg shadow-blue-200 text-sm font-bold uppercase tracking-wider mb-6 transform hover:scale-105 transition-transform cursor-default">
              <Zap className="w-4 h-4 fill-current" />
              <span>{t('loginPage.agenticAI')}</span>
            </div>
            <h2 className="text-4xl xl:text-5xl font-bold text-slate-900 mb-6 leading-tight">
              {t('loginPage.title')}{t('loginPage.title') ? <><br /></> : null}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-cyan-500">
                {t('loginPage.reimagined')}
              </span>
              {t('loginPage.titleSuffix') ? <><br /></> : null}{t('loginPage.titleSuffix')}
            </h2>
            <p className="text-slate-600 text-lg leading-relaxed max-w-lg break-keep">
              {t('loginPage.subtitle')}
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-12">
            {features.map((feature, idx) => {
              const Icon = feature.icon
              return (
                <div key={idx} className="bg-white border border-slate-200 rounded-xl p-5 hover:border-blue-300 hover:shadow-lg hover:shadow-blue-500/5 transition-all duration-300 group">
                  <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
                    <Icon className="w-5 h-5 text-blue-600" />
                  </div>
                  <h3 className="text-slate-800 font-bold mb-1">{feature.title}</h3>
                  <p className="text-slate-500 text-xs leading-relaxed font-medium">{feature.description}</p>
                </div>
              )
            })}
          </div>

          {/* Donation Card - Light Theme */}
          <div className="bg-white rounded-2xl p-1 shadow-xl shadow-slate-200/50 mt-auto border border-slate-100 transform hover:-translate-y-1 transition-transform duration-300">
            <div className="bg-gradient-to-br from-slate-50 to-white rounded-xl p-6 h-full flex items-center justify-between gap-6 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-32 h-32 bg-rose-100/30 rounded-full -mr-16 -mt-16 blur-xl" />

              <div className="flex-1 relative z-10">
                <div className="flex items-center gap-2 mb-2">
                  <Heart className="w-4 h-4 text-rose-500 fill-rose-500 animate-pulse" />
                  <span className="text-[10px] font-black uppercase tracking-wider text-rose-500">{t('loginPage.supportMission')}</span>
                </div>
                <p className="text-slate-800 font-bold text-sm mb-1">
                  {t('loginPage.keepFree')}
                </p>
                <p className="text-slate-500 text-xs italic font-medium">
                  {t('loginPage.quote')}
                </p>
              </div>
              <a
                href="https://ko-fi.com/pathlab"
                target="_blank"
                rel="noopener noreferrer"
                className="flex-shrink-0 relative z-10"
              >
                <Button className="bg-slate-900 hover:bg-slate-800 text-white font-bold shadow-lg shadow-slate-300 px-6 h-11 rounded-xl transition-all flex items-center gap-2">
                  {t('loginPage.donate')}
                  <ExternalLink className="w-3 h-3 opacity-70" />
                </Button>
              </a>
            </div>
          </div>

        </div>

        {/* Footer Text */}
        <div className="relative z-10 mt-8 text-center lg:text-left">
          <p className="text-slate-400 text-xs font-mono font-medium">{t('loginPage.buildVersion')}</p>
        </div>
      </div>

      <RegisterRequestModal isOpen={isRegisterOpen} onClose={() => setIsRegisterOpen(false)} turnstileSiteKey={turnstileSiteKey || undefined} />

      <DisclaimerModal
        isOpen={isTermsPreviewOpen}
        isLoading={false}
        onAccept={() => {}}
        onDecline={() => setIsTermsPreviewOpen(false)}
        previewOnly
        onClose={() => setIsTermsPreviewOpen(false)}
        onOpenPrivacyPolicy={() => setIsPrivacyPreviewOpen(true)}
      />

      <PrivacyPolicyModal
        isOpen={isPrivacyPreviewOpen}
        onClose={() => setIsPrivacyPreviewOpen(false)}
        onBackToTerms={() => {
          setIsPrivacyPreviewOpen(false)
          setIsTermsPreviewOpen(true)
        }}
      />

    </div>
  )
}

/**
 * LoginPage wrapper that fetches Turnstile settings and passes them down.
 * Turnstile script is only loaded on the login page, not globally.
 */
const NOTICE_CACHE_KEY = 'pathlab_notice_cache'

export default function LoginPage() {
  const [turnstileSiteKey, setTurnstileSiteKey] = React.useState<string>('')
  const [settingsLoaded, setSettingsLoaded] = React.useState(false)
  const [backendUnavailable, setBackendUnavailable] = React.useState(false)
  const [noticeMessage, setNoticeMessage] = React.useState<string | null>(null)
  const [noticeOpen, setNoticeOpen] = React.useState(false)

  React.useEffect(() => {
    getPublicSettings()
      .then((settings) => {
        if (settings.turnstile_enabled && settings.turnstile_site_key) {
          setTurnstileSiteKey(settings.turnstile_site_key)
        }
        setBackendUnavailable(false)
      })
      .catch((err) => {
        if (err instanceof ApiError && (err.isNetworkError() || err.isServerError())) {
          setBackendUnavailable(true)
        }
      })
      .finally(() => {
        setSettingsLoaded(true)
      })

    getPublicMaintenanceNotice()
      .then((notice) => {
        if (notice.active && notice.message) {
          localStorage.setItem(NOTICE_CACHE_KEY, JSON.stringify({ message: notice.message }))
          setNoticeMessage(notice.message)
          setNoticeOpen(true)
        } else {
          localStorage.removeItem(NOTICE_CACHE_KEY)
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && (err.isNetworkError() || err.isServerError())) {
          try {
            const cached = localStorage.getItem(NOTICE_CACHE_KEY)
            if (cached) {
              const { message } = JSON.parse(cached)
              if (message) {
                setNoticeMessage(message)
                setNoticeOpen(true)
              }
            }
          } catch { /* ignore */ }
        }
      })
  }, [])

  if (!settingsLoaded) {
    return null
  }

  return (
    <>
      <LoginPageInner backendUnavailable={backendUnavailable} turnstileSiteKey={turnstileSiteKey || undefined} />
      <MaintenanceNoticeModal
        isOpen={noticeOpen}
        message={noticeMessage ?? ''}
        onDismiss={() => setNoticeOpen(false)}
      />
    </>
  )
}
