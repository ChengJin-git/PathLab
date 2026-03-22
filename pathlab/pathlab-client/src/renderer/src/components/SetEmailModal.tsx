import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Mail, Loader2 } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { updateCurrentUser, ApiError } from '../api'
import { useAuth } from '../contexts/AuthContext'

interface SetEmailModalProps {
  isOpen: boolean
  onClose: () => void
}

export function SetEmailModal({ isOpen, onClose }: SetEmailModalProps) {
  const { t } = useTranslation()
  const { user, refreshUser } = useAuth()
  const [email, setEmail] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  if (!isOpen) return null

  const resetForm = () => {
    setEmail('')
    setError(null)
    setSuccess(false)
  }

  const handleClose = () => {
    resetForm()
    onClose()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const trimmed = email.trim()
    if (!trimmed) {
      setError(t('setEmail.emailRequired'))
      return
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!emailRegex.test(trimmed)) {
      setError(t('setEmail.emailInvalid'))
      return
    }

    setIsSubmitting(true)
    try {
      await updateCurrentUser({ email: trimmed })
      await refreshUser()
      setSuccess(true)
      setTimeout(() => {
        handleClose()
      }, 1500)
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError(t('setEmail.emailTaken'))
      } else {
        setError(err instanceof Error ? err.message : t('setEmail.genericError'))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-2 sm:p-4 animate-in fade-in duration-200">
      <div className="bg-white rounded-xl sm:rounded-2xl shadow-2xl max-w-md w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200">
        <div className="p-4 sm:p-6 border-b border-slate-100 bg-slate-50/50 flex items-center gap-3">
          <div className="p-2 bg-primary-100 rounded-lg">
            <Mail className="w-4 h-4 sm:w-5 sm:h-5 text-primary-600" />
          </div>
          <h3 className="text-base sm:text-lg font-bold text-gray-900">
            {t('setEmail.title')}
          </h3>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="p-4 sm:p-6 space-y-4">
            {user?.email && (
              <div className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2">
                {t('setEmail.currentEmail')}{' '}
                <span className="font-medium text-slate-700">{user.email}</span>
              </div>
            )}

            <div className="space-y-1.5">
              <Label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                {t('setEmail.newEmail')}
              </Label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t('setEmail.emailPlaceholder')}
                className="h-9 text-sm"
                autoComplete="email"
                required
                disabled={isSubmitting || success}
              />
            </div>

            {error && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
            {success && (
              <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
                {t('setEmail.success')}
              </p>
            )}
          </div>

          <div className="p-4 sm:p-6 bg-gray-50 flex justify-end gap-3 border-t border-gray-100">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              {t('common.cancel')}
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={isSubmitting || success}
              className="bg-primary-600 hover:bg-primary-700 text-white"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                  {t('setEmail.submitting')}
                </>
              ) : (
                t('setEmail.submit')
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
