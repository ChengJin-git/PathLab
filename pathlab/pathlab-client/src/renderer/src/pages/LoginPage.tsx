/**
 * PathLab Login Page
 *
 * Landing page with username/password login.
 * Registration is only available through admin in Settings.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { GoogleReCaptchaProvider, useGoogleReCaptcha } from 'react-google-recaptcha-v3'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { Microscope, Brain, Shield, Zap, LogIn, Loader2, User, Lock, Heart, ExternalLink, AlertTriangle } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { getPublicSettings, ApiError } from '../api'

/**
 * Inner login page component that uses the reCAPTCHA hook.
 * Must be rendered inside GoogleReCaptchaProvider.
 */
function LoginPageInner({ backendUnavailable = false }: { backendUnavailable?: boolean }) {
  const navigate = useNavigate()
  const { login, isLoading, error, isLoggedIn } = useAuth()
  const { executeRecaptcha } = useGoogleReCaptcha()
  const { t } = useTranslation()

  // Form state
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [formError, setFormError] = React.useState<string | null>(null)

  // If already logged in, redirect to AI chat
  React.useEffect(() => {
    if (isLoggedIn) {
      navigate('/dashboard')
    }
  }, [isLoggedIn, navigate])

  // Hide reCAPTCHA badge on unmount (when navigating away from login page)
  React.useEffect(() => {
    return () => {
      const badge = document.querySelector('.grecaptcha-badge') as HTMLElement | null
      if (badge) {
        badge.style.visibility = 'hidden'
      }
    }
  }, [])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    if (!username || !password) {
      setFormError(t('common.pleaseEnterUsernameAndPassword'))
      return
    }

    // Get reCAPTCHA token if available
    let recaptchaToken: string | undefined
    if (executeRecaptcha) {
      try {
        recaptchaToken = await executeRecaptcha('login')
      } catch (err) {
        console.error('reCAPTCHA error:', err)
      }
    }

    const success = await login(username, password, recaptchaToken)
    if (success) {
      navigate('/dashboard')
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

            <Button
              type="submit"
              disabled={isLoading}
              className="w-full h-11 bg-slate-900 hover:bg-slate-800 text-white font-medium rounded-lg shadow-lg hover:shadow-xl transition-all flex items-center justify-center gap-2"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
              {t('common.signIn')}
            </Button>

            <p className="text-center text-xs text-slate-400 mt-6">
              © 2026 <a href="https://smartlab.cse.ust.hk/" target="_blank" rel="noopener noreferrer">SmartLab</a> · {t('common.protectedByRecaptcha')}
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

    </div>
  )
}

/**
 * LoginPage wrapper that conditionally provides GoogleReCaptchaProvider.
 * reCAPTCHA is only loaded on the login page, not globally.
 */
export default function LoginPage() {
  const [recaptchaSiteKey, setRecaptchaSiteKey] = React.useState<string>('')
  const [recaptchaEnabled, setRecaptchaEnabled] = React.useState<boolean>(false)
  const [settingsLoaded, setSettingsLoaded] = React.useState(false)
  const [backendUnavailable, setBackendUnavailable] = React.useState(false)

  React.useEffect(() => {
    getPublicSettings()
      .then((settings) => {
        setRecaptchaEnabled(settings.recaptcha_enabled)
        setRecaptchaSiteKey(settings.recaptcha_site_key)
        setBackendUnavailable(false)
      })
      .catch((err) => {
        // If backend is unreachable (network error or nginx 502/503), show maintenance banner
        if (err instanceof ApiError && (err.isNetworkError() || err.isServerError())) {
          setBackendUnavailable(true)
        }
        // Continue without reCAPTCHA either way
      })
      .finally(() => {
        setSettingsLoaded(true)
      })
  }, [])

  // Show reCAPTCHA badge when on login page, hide on unmount
  React.useEffect(() => {
    const badge = document.querySelector('.grecaptcha-badge') as HTMLElement | null
    if (badge) {
      badge.style.visibility = 'visible'
    }
    return () => {
      const badge = document.querySelector('.grecaptcha-badge') as HTMLElement | null
      if (badge) {
        badge.style.visibility = 'hidden'
      }
    }
  })

  if (!settingsLoaded) {
    return null
  }

  if (recaptchaEnabled && recaptchaSiteKey) {
    return (
      <GoogleReCaptchaProvider reCaptchaKey={recaptchaSiteKey}>
        <LoginPageInner backendUnavailable={backendUnavailable} />
      </GoogleReCaptchaProvider>
    )
  }

  return <LoginPageInner backendUnavailable={backendUnavailable} />
}
