import { useState } from 'react'
import { InstallationContact } from './legal/InstallationContact'
import { useTranslation } from 'react-i18next'
import { KeyRound, Loader2, Eye, EyeOff } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { changePassword } from '../api/auth'
import { ApiError } from '../api/client'
import { ModalShell } from './ui/modal-shell'

interface ChangePasswordModalProps {
  isOpen: boolean
  onClose: () => void
}

export function ChangePasswordModal({ isOpen, onClose }: ChangePasswordModalProps) {
  const { t } = useTranslation()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const resetForm = () => {
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setError(null)
    setSuccess(false)
    setShowCurrent(false)
    setShowNew(false)
    setShowConfirm(false)
  }

  const handleClose = () => {
    resetForm()
    onClose()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (newPassword !== confirmPassword) {
      setError(t('changePassword.mismatch'))
      return
    }

    if (!newPassword) {
      setError(t('changePassword.newPasswordRequired'))
      return
    }

    setIsSubmitting(true)
    try {
      await changePassword(currentPassword, newPassword)
      setSuccess(true)
      setTimeout(() => {
        handleClose()
      }, 1500)
    } catch (err) {
      if (err instanceof ApiError && err.details === 'CURRENT_PASSWORD_INCORRECT') {
        setError(t('changePassword.currentPasswordIncorrect'))
      } else {
        setError(err instanceof Error ? err.message : t('changePassword.genericError'))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <ModalShell isOpen={isOpen} onClose={handleClose} maxWidth="md">
        <div className="p-4 sm:p-6 border-b border-slate-100 bg-slate-50/50 flex items-center gap-3">
          <div className="p-2 bg-primary-100 rounded-lg">
            <KeyRound className="w-4 h-4 sm:w-5 sm:h-5 text-primary-600" />
          </div>
          <h3 className="text-base sm:text-lg font-bold text-gray-900">
            {t('changePassword.title')}
          </h3>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="p-4 sm:p-6 space-y-4">
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                {t('changePassword.currentPassword')}
              </Label>
              <div className="relative">
                <Input
                  type={showCurrent ? 'text' : 'password'}
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="pr-10 h-9 text-sm"
                  autoComplete="current-password"
                  required
                  disabled={isSubmitting || success}
                />
                <button
                  type="button"
                  onClick={() => setShowCurrent((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  tabIndex={-1}
                >
                  {showCurrent ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                {t('changePassword.newPassword')}
              </Label>
              <div className="relative">
                <Input
                  type={showNew ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="pr-10 h-9 text-sm"
                  autoComplete="new-password"
                  required
                  disabled={isSubmitting || success}
                />
                <button
                  type="button"
                  onClick={() => setShowNew((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  tabIndex={-1}
                >
                  {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                {t('changePassword.confirmPassword')}
              </Label>
              <div className="relative">
                <Input
                  type={showConfirm ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="pr-10 h-9 text-sm"
                  autoComplete="new-password"
                  required
                  disabled={isSubmitting || success}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  tabIndex={-1}
                >
                  {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <p className="text-[11px] text-slate-400 leading-relaxed">
              {t('changePassword.forgotHint')}{' '}
              <InstallationContact className="text-slate-500 underline underline-offset-2 hover:text-slate-700 transition-colors" />
            </p>

            {error && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
            {success && (
              <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
                {t('changePassword.success')}
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
                  {t('changePassword.submitting')}
                </>
              ) : (
                t('changePassword.submit')
              )}
            </Button>
          </div>
        </form>
    </ModalShell>
  )
}
