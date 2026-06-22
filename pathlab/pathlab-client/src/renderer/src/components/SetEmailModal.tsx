import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Mail, Loader2 } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { updateCurrentUser, ApiError, CurrentUserUpdateRequest } from '../api'
import { useAuth } from '../contexts/AuthContext'
import { ModalShell } from './ui/modal-shell'

interface SetEmailModalProps {
  isOpen: boolean
  onClose: () => void
}

export function SetEmailModal({ isOpen, onClose }: SetEmailModalProps) {
  const { t } = useTranslation()
  const { user, refreshUser } = useAuth()
  
  const [email, setEmail] = useState('')
  const [notifySuccess, setNotifySuccess] = useState(true)
  const [notifyFailed, setNotifyFailed] = useState(false)
  const [notifyCancelled, setNotifyCancelled] = useState(false)
  
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (isOpen && user) {
      setEmail('')
      setNotifySuccess(user.notify_on_success ?? true)
      setNotifyFailed(user.notify_on_failed ?? false)
      setNotifyCancelled(user.notify_on_cancelled ?? false)
      setError(null)
      setSuccess(false)
    }
  }, [isOpen, user])

  const handleClose = () => {
    onClose()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const trimmed = email.trim()
    const updateData: CurrentUserUpdateRequest = {
      notify_on_success: notifySuccess,
      notify_on_failed: notifyFailed,
      notify_on_cancelled: notifyCancelled
    }

    if (trimmed) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
      if (!emailRegex.test(trimmed)) {
        setError(t('setEmail.emailInvalid'))
        return
      }
      updateData.email = trimmed
    }

    setIsSubmitting(true)
    try {
      await updateCurrentUser(updateData)
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
    <ModalShell isOpen={isOpen} onClose={handleClose} maxWidth="md">
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
            {!user?.email && (
              <div className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2">
                {t('setEmail.noEmailSet')}
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
                disabled={isSubmitting || success}
              />
              <p className="text-xs text-slate-400">
                {t('setEmail.emailHint')}
              </p>
            </div>

            <div className="border-t border-slate-100 pt-4">
              <Label className="text-xs font-semibold text-slate-700 uppercase tracking-wide block mb-0.5">
                {t('setEmail.notifications')}
              </Label>
              <p className="text-xs text-slate-400 mb-2">
                {t('setEmail.notifyHint')}
              </p>
              
              <div className="space-y-1">
                <label className="flex items-center gap-2.5 py-1 cursor-pointer group">
                  <input 
                    type="checkbox"
                    checked={notifySuccess}
                    onChange={(e) => setNotifySuccess(e.target.checked)}
                    disabled={isSubmitting || success}
                    className="w-4 h-4 rounded accent-primary-600 cursor-pointer"
                  />
                  <span className="text-sm text-slate-700 group-hover:text-slate-900 transition-colors">
                    {t('setEmail.notifySuccess')}
                  </span>
                </label>

                <label className="flex items-center gap-2.5 py-1 cursor-pointer group">
                  <input 
                    type="checkbox"
                    checked={notifyFailed}
                    onChange={(e) => setNotifyFailed(e.target.checked)}
                    disabled={isSubmitting || success}
                    className="w-4 h-4 rounded accent-primary-600 cursor-pointer"
                  />
                  <span className="text-sm text-slate-700 group-hover:text-slate-900 transition-colors">
                    {t('setEmail.notifyFailed')}
                  </span>
                </label>

                <label className="flex items-center gap-2.5 py-1 cursor-pointer group">
                  <input 
                    type="checkbox"
                    checked={notifyCancelled}
                    onChange={(e) => setNotifyCancelled(e.target.checked)}
                    disabled={isSubmitting || success}
                    className="w-4 h-4 rounded accent-primary-600 cursor-pointer"
                  />
                  <span className="text-sm text-slate-700 group-hover:text-slate-900 transition-colors">
                    {t('setEmail.notifyCancelled')}
                  </span>
                </label>
              </div>
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
    </ModalShell>
  )
}
