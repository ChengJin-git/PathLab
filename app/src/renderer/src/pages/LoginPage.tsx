/** Public sign-in. Access requests and the existing captcha/maintenance flows
 * remain part of the authentication entry point. */
import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { MotionConfig } from 'framer-motion'
import { AlertCircle, AlertTriangle, ArrowLeft, ArrowRight, ChevronRight, Eye, EyeOff, FileText, Loader2, ShieldCheck } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { Input } from '../components/ui/input'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import { DisclaimerModal } from '../components/DisclaimerModal'
import { PrivacyPolicyModal } from '../components/PrivacyPolicyModal'
import { getPublicSettings, ApiError } from '../api'
import { RegisterRequestModal } from '../components/RegisterRequestModal'
import { TencentCaptcha } from '../components/TencentCaptcha'
import { LoginShowcase } from '../components/landing/LoginShowcase'
import pathlabLogo from '../../public/images/pathlab-logo.png'
import { usePointerGlow } from '../components/landing/usePointerGlow'
import '../components/landing/public-experience.css'

function LoginPageInner({ backendUnavailable = false, captchaProvider, captchaSiteKey }: { backendUnavailable?: boolean; captchaProvider?: 'turnstile' | 'tencent' | null; captchaSiteKey?: string }) {
  const navigate = useNavigate()
  const { login, isLoading, error, isLoggedIn } = useAuth()
  const { t } = useTranslation()
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [showPassword, setShowPassword] = React.useState(false)
  const [formError, setFormError] = React.useState<string | null>(null)
  const [isRegisterOpen, setIsRegisterOpen] = React.useState(false)
  const [isTermsPreviewOpen, setIsTermsPreviewOpen] = React.useState(false)
  const [isPrivacyPreviewOpen, setIsPrivacyPreviewOpen] = React.useState(false)
  const usernameRef = React.useRef<HTMLInputElement>(null)
  const passwordRef = React.useRef<HTMLInputElement>(null)
  const [turnstileToken, setTurnstileToken] = React.useState<string | undefined>(undefined)
  const turnstileRef = React.useRef<HTMLDivElement>(null)
  const turnstileWidgetId = React.useRef<string | null>(null)
  const [tencentTicket, setTencentTicket] = React.useState<string | undefined>(undefined)
  const [tencentRandstr, setTencentRandstr] = React.useState<string | undefined>(undefined)
  const shellRef = React.useRef<HTMLDivElement>(null)
  usePointerGlow(shellRef)

  const captchaRequired = Boolean(captchaProvider && captchaSiteKey)
  const captchaComplete = !captchaRequired || (
    captchaProvider === 'turnstile' ? Boolean(turnstileToken) : Boolean(tencentTicket && tencentRandstr)
  )
  const handleTencentVerify = React.useCallback((ticket: string, randstr: string) => {
    setTencentTicket(ticket)
    setTencentRandstr(randstr)
  }, [])
  const resetTencentCaptcha = React.useCallback(() => {
    setTencentTicket(undefined)
    setTencentRandstr(undefined)
  }, [])

  React.useEffect(() => {
    if (isLoggedIn) navigate('/dashboard')
  }, [isLoggedIn, navigate])

  React.useEffect(() => {
    if (captchaProvider !== 'turnstile' || !captchaSiteKey || !turnstileRef.current) return
    let disposed = false
    const renderWidget = () => {
      if (disposed || !turnstileRef.current || turnstileWidgetId.current !== null) return
      turnstileWidgetId.current = (window as any).turnstile.render(turnstileRef.current, {
        sitekey: captchaSiteKey,
        callback: (token: string) => setTurnstileToken(token),
        'expired-callback': () => setTurnstileToken(undefined),
        'error-callback': () => setTurnstileToken(undefined),
        theme: 'light',
        size: 'flexible',
      })
    }
    let script: HTMLScriptElement | undefined
    if ((window as any).turnstile) {
      renderWidget()
    } else {
      script = document.createElement('script')
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
      script.async = true
      script.onload = renderWidget
      document.head.appendChild(script)
    }
    return () => {
      disposed = true
      if (script) script.onload = null
      if (turnstileWidgetId.current !== null && (window as any).turnstile) {
        try { (window as any).turnstile.remove(turnstileWidgetId.current) } catch { /* already removed */ }
        turnstileWidgetId.current = null
      }
    }
  }, [captchaProvider, captchaSiteKey])

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault()
    setFormError(null)
    if (!username || !password) {
      setFormError(t('common.pleaseEnterUsernameAndPassword'))
      if (!username) usernameRef.current?.focus()
      else passwordRef.current?.focus()
      return
    }
    const success = await login(username, password, turnstileToken, tencentTicket, tencentRandstr)
    if (success) {
      navigate('/dashboard')
    } else if (captchaProvider === 'turnstile' && turnstileWidgetId.current !== null && (window as any).turnstile) {
      try {
        (window as any).turnstile.reset(turnstileWidgetId.current)
        setTurnstileToken(undefined)
      } catch { /* widget may have unmounted */ }
    } else if (captchaProvider === 'tencent') {
      resetTencentCaptcha()
    }
  }

  const displayedError = formError || error

  return (
    <div ref={shellRef} data-testid="login-page-shell" className="public-experience public-login" data-public-page="login">
      <LoginShowcase />
      <main className="login-access">
        <div className="login-access__nav">
          <Link to="/" className="login-back" aria-label={t('publicExperience.backHome')}>
            <ArrowLeft size={15} />
            <span className="login-back__text">{t('publicExperience.backHome')}</span>
            <img className="login-back__brand" src={pathlabLogo} width="998" height="250" alt="PathLab" />
          </Link>
          <LanguageSwitcher className="public-language" />
        </div>
        <div className="login-access__form-wrap">
          <h1>{t('auth.welcomeBack')}</h1>
          <p className="login-access__subtitle">{t('publicExperience.loginSubtitle')}</p>
          <form onSubmit={handleLogin} className="login-form" aria-busy={isLoading}>
            <div className="login-field">
              <label htmlFor="username">{t('auth.username')}</label>
              <Input ref={usernameRef} id="username" name="username" type="text" placeholder={t('loginPage.enterUsername')} value={username} onChange={event => setUsername(event.target.value)} disabled={isLoading} autoComplete="username" autoCapitalize="none" spellCheck={false} aria-required="true" aria-invalid={Boolean(formError && !username)} aria-describedby={displayedError ? 'login-error' : undefined} />
            </div>
            <div className="login-field">
              <label htmlFor="password">{t('auth.password')}</label>
              <div className="login-field__input">
                <Input ref={passwordRef} id="password" name="password" type={showPassword ? 'text' : 'password'} placeholder={t('loginPage.enterPassword')} value={password} onChange={event => setPassword(event.target.value)} disabled={isLoading} autoComplete="current-password" aria-required="true" aria-invalid={Boolean(formError && !password)} aria-describedby={displayedError ? 'login-error' : undefined} />
                <button type="button" className="login-password-toggle" onClick={() => setShowPassword(value => !value)} aria-label={t(showPassword ? 'publicExperience.hidePassword' : 'publicExperience.showPassword')} aria-pressed={showPassword} aria-controls="password" disabled={isLoading}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button>
              </div>
            </div>
            {backendUnavailable && <div className="login-message login-message--maintenance" role="status"><AlertTriangle size={16} /><p>{t('auth.systemMaintenance')}</p></div>}
            {displayedError && <div id="login-error" className="login-message" role="alert"><AlertCircle size={16} /><p>{displayedError}</p></div>}
            {captchaProvider === 'turnstile' && captchaSiteKey && <div ref={turnstileRef} className="w-full" />}
            {captchaProvider === 'tencent' && captchaSiteKey && <TencentCaptcha appId={captchaSiteKey} onVerify={handleTencentVerify} onExpire={resetTencentCaptcha} onError={resetTencentCaptcha} />}
            <button type="submit" disabled={isLoading || !captchaComplete} className="public-button login-form__submit">{isLoading ? <><Loader2 size={17} className="animate-spin" />{t('publicExperience.signingIn')}</> : <>{t('common.signIn')}<ArrowRight size={17} /></>}</button>
          </form>
          <div className="login-request"><span>{t('publicExperience.noAccount')}</span><button type="button" onClick={() => setIsRegisterOpen(true)}>{t('loginPage.requestAccess')}</button></div>
          <div className="login-legal">
            <p>{t('loginPage.legalNotice')}</p>
            <div className="login-legal__links">
              <button type="button" onClick={() => setIsTermsPreviewOpen(true)}>
                <FileText size={17} strokeWidth={1.6} /><span>{t('loginPage.viewTerms')}</span><ChevronRight size={15} />
              </button>
              <button type="button" onClick={() => setIsPrivacyPreviewOpen(true)}>
                <ShieldCheck size={17} strokeWidth={1.6} /><span>{t('loginPage.viewPrivacy')}</span><ChevronRight size={15} />
              </button>
            </div>
          </div>
        </div>
        <div className="login-access__footer">
          <span>© 2026 <a href="https://smartx.ust.hk/" target="_blank" rel="noopener noreferrer">SmartXLab</a></span>
          {captchaProvider && <span>{t(captchaProvider === 'turnstile' ? 'common.protectedByTurnstile' : 'common.protectedByTencent')}</span>}
        </div>
      </main>
      <RegisterRequestModal isOpen={isRegisterOpen} onClose={() => setIsRegisterOpen(false)} captchaProvider={captchaProvider} captchaSiteKey={captchaSiteKey || undefined} onOpenPrivacyPolicy={() => setIsPrivacyPreviewOpen(true)} privacyOpen={isPrivacyPreviewOpen} />
      <DisclaimerModal isOpen={isTermsPreviewOpen} isLoading={false} onAccept={() => {}} onDecline={() => setIsTermsPreviewOpen(false)} previewOnly onClose={() => setIsTermsPreviewOpen(false)} onOpenPrivacyPolicy={() => { setIsTermsPreviewOpen(false); setIsPrivacyPreviewOpen(true) }} />
      <PrivacyPolicyModal isOpen={isPrivacyPreviewOpen} onClose={() => setIsPrivacyPreviewOpen(false)} onBackToTerms={() => { setIsPrivacyPreviewOpen(false); setIsTermsPreviewOpen(true) }} />
    </div>
  )
}

export default function LoginPage() {
  const [captchaProvider, setCaptchaProvider] = React.useState<'turnstile' | 'tencent' | null>(null)
  const [captchaSiteKey, setCaptchaSiteKey] = React.useState<string>('')
  const [settingsLoaded, setSettingsLoaded] = React.useState(false)
  const [backendUnavailable, setBackendUnavailable] = React.useState(false)

  React.useEffect(() => {
    getPublicSettings()
      .then((settings) => {
        if (settings.captcha_provider && settings.captcha_site_key) {
          setCaptchaProvider(settings.captcha_provider)
          setCaptchaSiteKey(settings.captcha_site_key)
        }
        setBackendUnavailable(false)
      })
      .catch((err) => {
        if (err instanceof ApiError && (err.isNetworkError() || err.isServerError())) setBackendUnavailable(true)
      })
      .finally(() => setSettingsLoaded(true))
  }, [])

  return (
    <MotionConfig reducedMotion="user">
      <LoginPageInner backendUnavailable={backendUnavailable && settingsLoaded} captchaProvider={captchaProvider} captchaSiteKey={captchaSiteKey || undefined} />
    </MotionConfig>
  )
}
