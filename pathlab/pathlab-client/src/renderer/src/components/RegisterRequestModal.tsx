import React from 'react'
import { useTranslation } from 'react-i18next'
import { UserPlus, Mail, User, Lock, CheckCircle, X, Loader2, Info } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { requestAccess } from '../api/auth'
import { ApiError } from '../api/client'
import { ModalShell } from './ui/modal-shell'
import { TencentCaptcha } from './TencentCaptcha'

interface Props {
  isOpen: boolean
  onClose: () => void
  captchaProvider?: 'turnstile' | 'tencent' | null
  captchaSiteKey?: string
}

type Step = 'form' | 'success'

export function RegisterRequestModal({ isOpen, onClose, captchaProvider, captchaSiteKey }: Props) {
  const { t } = useTranslation()

  const [step, setStep] = React.useState<Step>('form')
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [confirmPassword, setConfirmPassword] = React.useState('')
  const [registrationEmail, setRegistrationEmail] = React.useState('')
  const [nickname, setNickname] = React.useState('')
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const [turnstileToken, setTurnstileToken] = React.useState<string | undefined>(undefined)
  const turnstileRef = React.useRef<HTMLDivElement>(null)
  const turnstileWidgetId = React.useRef<string | null>(null)

  const [tencentTicket, setTencentTicket] = React.useState<string | undefined>(undefined)
  const [tencentRandstr, setTencentRandstr] = React.useState<string | undefined>(undefined)

  React.useEffect(() => {
    if (isOpen) {
      setStep('form')
      setUsername('')
      setPassword('')
      setConfirmPassword('')
      setRegistrationEmail('')
      setNickname('')
      setError(null)
      setIsSubmitting(false)
      setTurnstileToken(undefined)
      setTencentTicket(undefined)
      setTencentRandstr(undefined)
    } else {
      if (turnstileWidgetId.current !== null && (window as any).turnstile) {
        try {
          (window as any).turnstile.remove(turnstileWidgetId.current)
        } catch { /* ignore */ }
        turnstileWidgetId.current = null
      }
    }
  }, [isOpen])

  React.useEffect(() => {
    if (!isOpen || captchaProvider !== 'turnstile' || !captchaSiteKey || !turnstileRef.current) return
    if (turnstileWidgetId.current !== null) return

    const render = () => {
      if (!turnstileRef.current || turnstileWidgetId.current !== null) return
      if (!(window as any).turnstile) return
      turnstileWidgetId.current = (window as any).turnstile.render(turnstileRef.current, {
        sitekey: captchaSiteKey,
        callback: (token: string) => setTurnstileToken(token),
        'expired-callback': () => setTurnstileToken(undefined),
        'error-callback': () => setTurnstileToken(undefined),
        theme: 'light',
        size: 'flexible',
      })
    }

    if ((window as any).turnstile) {
      render()
    } else {
      const existing = document.querySelector('script[src*="challenges.cloudflare.com/turnstile"]')
      if (existing) {
        existing.addEventListener('load', render, { once: true })
      }
    }
  }, [isOpen, captchaProvider, captchaSiteKey])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!username.trim()) { setError(t('registerModal.errorUsernameRequired')); return }
    if (password.length < 6) { setError(t('registerModal.errorPasswordTooShort')); return }
    if (password !== confirmPassword) { setError(t('registerModal.errorPasswordMismatch')); return }
    if (!registrationEmail.trim()) { setError(t('registerModal.errorEmailRequired')); return }

    setIsSubmitting(true)
    try {
      await requestAccess({
        username: username.trim(),
        password,
        registration_email: registrationEmail.trim(),
        nickname: nickname.trim() || undefined,
        turnstile_token: turnstileToken,
        tencent_captcha_token: tencentTicket,
        tencent_captcha_randstr: tencentRandstr,
      })
      setStep('success')
    } catch (err) {
      if (captchaProvider === 'turnstile' && turnstileWidgetId.current !== null && (window as any).turnstile) {
        try {
          (window as any).turnstile.reset(turnstileWidgetId.current)
          setTurnstileToken(undefined)
        } catch { /* ignore */ }
      } else if (captchaProvider === 'tencent') {
        setTencentTicket(undefined)
        setTencentRandstr(undefined)
      }
      if (err instanceof ApiError) {
        const detail = err.details as string | undefined
        if (detail === 'REGISTRATION_EMAIL_NOT_EDUCATIONAL') {
          setError(t('registerModal.errorEmailNotEducational'))
        } else if (detail === 'REGISTER_USER_ALREADY_EXISTS') {
          setError(t('registerModal.errorUsernameTaken'))
        } else if (detail === 'REGISTER_PASSWORD_TOO_SHORT') {
          setError(t('registerModal.errorPasswordTooShort'))
        } else if (detail === 'TURNSTILE_TOKEN_REQUIRED' || detail === 'TURNSTILE_VERIFICATION_FAILED') {
          setError(t('registerModal.errorTurnstileFailed'))
        } else {
          setError(err.message || t('registerModal.errorGeneric'))
        }
      } else {
        setError(t('registerModal.errorGeneric'))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <ModalShell isOpen={isOpen} maxWidth="md" className="relative">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 rounded-full text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>

        {step === 'form' ? (
          <div className="p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
                <UserPlus className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-slate-900">{t('registerModal.title')}</h2>
                <p className="text-xs text-slate-500">{t('registerModal.subtitle')}</p>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1">
                <label htmlFor="reg-username" className="text-xs font-semibold text-slate-500">{t('registerModal.username')}</label>
                <div className="relative group">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                  <Input id="reg-username" type="text" placeholder={t('registerModal.usernamePlaceholder')} value={username} onChange={(e) => setUsername(e.target.value)} className="pl-10 h-10 bg-slate-50 border-slate-200 focus:bg-white" disabled={isSubmitting} autoComplete="username" />
                </div>
              </div>

              <div className="space-y-1">
                <label htmlFor="reg-nickname" className="text-xs font-semibold text-slate-500">
                  {t('registerModal.nickname')}<span className="ml-1 font-normal text-slate-400">({t('common.optional')})</span>
                </label>
                <Input id="reg-nickname" type="text" placeholder={t('registerModal.nicknamePlaceholder')} value={nickname} onChange={(e) => setNickname(e.target.value)} className="h-10 bg-slate-50 border-slate-200 focus:bg-white" disabled={isSubmitting} />
              </div>

              <div className="space-y-1">
                <label htmlFor="reg-password" className="text-xs font-semibold text-slate-500">{t('registerModal.password')}</label>
                <div className="relative group">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                  <Input id="reg-password" type="password" placeholder={t('registerModal.passwordPlaceholder')} value={password} onChange={(e) => setPassword(e.target.value)} className="pl-10 h-10 bg-slate-50 border-slate-200 focus:bg-white" disabled={isSubmitting} autoComplete="new-password" />
                </div>
              </div>

              <div className="space-y-1">
                <label htmlFor="reg-confirm-password" className="text-xs font-semibold text-slate-500">{t('registerModal.confirmPassword')}</label>
                <div className="relative group">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                  <Input id="reg-confirm-password" type="password" placeholder={t('registerModal.confirmPasswordPlaceholder')} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="pl-10 h-10 bg-slate-50 border-slate-200 focus:bg-white" disabled={isSubmitting} autoComplete="new-password" />
                </div>
              </div>

              <div className="space-y-1">
                <label htmlFor="reg-email" className="text-xs font-semibold text-slate-500">{t('registerModal.educationalEmail')}</label>
                <div className="relative group">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                  <Input id="reg-email" type="email" placeholder={t('registerModal.educationalEmailPlaceholder')} value={registrationEmail} onChange={(e) => setRegistrationEmail(e.target.value)} className="pl-10 h-10 bg-slate-50 border-slate-200 focus:bg-white" disabled={isSubmitting} autoComplete="email" />
                </div>
                <div className="flex items-start gap-1.5 mt-1.5 px-1">
                  <Info className="w-3 h-3 text-slate-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-slate-400 leading-relaxed">{t('registerModal.educationalEmailHint')}</p>
                </div>
              </div>

              {error && (
                <div className="p-3 bg-red-50 border border-red-100 rounded-lg text-red-600 text-sm flex items-start gap-2 animate-in fade-in slide-in-from-top-1">
                  <div className="w-1 h-4 mt-0.5 rounded-full bg-red-500 flex-shrink-0" />
                  <p>{error}</p>
                </div>
              )}

              {captchaProvider === 'turnstile' && captchaSiteKey && (
                <div ref={turnstileRef} className="w-full" />
              )}
              {captchaProvider === 'tencent' && captchaSiteKey && (
                <TencentCaptcha
                  appId={captchaSiteKey}
                  onVerify={(ticket, randstr) => {
                    setTencentTicket(ticket)
                    setTencentRandstr(randstr)
                  }}
                  onExpire={() => {
                    setTencentTicket(undefined)
                    setTencentRandstr(undefined)
                  }}
                  onError={() => {
                    setTencentTicket(undefined)
                    setTencentRandstr(undefined)
                  }}
                />
              )}

              <Button type="submit" disabled={isSubmitting || (!!captchaSiteKey && !turnstileToken && !tencentTicket)} className="w-full h-10 bg-slate-900 hover:bg-slate-800 text-white font-medium rounded-lg">
                {isSubmitting
                  ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />{t('registerModal.submitting')}</>
                  : <><UserPlus className="w-4 h-4 mr-2" />{t('registerModal.submit')}</>
                }
              </Button>
            </form>

            <p className="text-center text-xs text-slate-400 mt-4">{t('registerModal.adminNote')}</p>
          </div>
        ) : (
          <div className="p-8 text-center">
            <div className="w-16 h-16 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-4">
              <CheckCircle className="w-8 h-8 text-emerald-500" />
            </div>
            <h2 className="text-xl font-bold text-slate-900 mb-2">{t('registerModal.successTitle')}</h2>
            <p className="text-sm text-slate-600 mb-6 leading-relaxed">{t('registerModal.successMessage')}</p>
            <Button type="button" onClick={onClose} className="px-8">{t('common.close')}</Button>
          </div>
        )}
    </ModalShell>
  )
}
