import { useTranslation } from 'react-i18next'
import { UserPlus } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'

export interface CreateUserModalProps {
  createForm: { username: string; password: string; nickname: string; role: string }
  onCreateFormChange: (form: { username: string; password: string; nickname: string; role: string }) => void
  onSubmit: () => void
  onClose: () => void
  isCreating: boolean
  error?: string | null
}

export function CreateUserModal({ createForm, onCreateFormChange, onSubmit, onClose, isCreating, error }: CreateUserModalProps) {
  const { t } = useTranslation()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <UserPlus className="w-5 h-5 mr-2 text-primary-600" />
          {t('settings.createUserModal.title')}
        </h3>
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}
        <div className="space-y-4">
          <div>
            <Label className="text-sm text-gray-600">{t('settings.createUserModal.usernameRequired')}</Label>
            <Input
              value={createForm.username}
              onChange={(e) => onCreateFormChange({ ...createForm, username: e.target.value })}
              className="mt-1"
              placeholder={t('settings.createUserModal.enterUsername')}
              disabled={isCreating}
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">{t('settings.createUserModal.passwordRequired')}</Label>
            <Input
              type="password"
              value={createForm.password}
              onChange={(e) => onCreateFormChange({ ...createForm, password: e.target.value })}
              className="mt-1"
              placeholder={t('settings.createUserModal.minSixChars')}
              disabled={isCreating}
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">{t('settings.createUserModal.nickname')}</Label>
            <Input
              value={createForm.nickname}
              onChange={(e) => onCreateFormChange({ ...createForm, nickname: e.target.value })}
              className="mt-1"
              placeholder={t('settings.createUserModal.displayNameOptional')}
              disabled={isCreating}
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">{t('settings.createUserModal.role')}</Label>
            <select
              value={createForm.role}
              onChange={(e) => onCreateFormChange({ ...createForm, role: e.target.value })}
              className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              disabled={isCreating}
            >
              <option value="admin">{t('settings.createUserModal.roleAdmin')}</option>
              <option value="pathologist">{t('settings.createUserModal.rolePathologist')}</option>
              <option value="guest">{t('settings.createUserModal.roleGuest')}</option>
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="outline" onClick={onClose} disabled={isCreating}>
            {t('settings.createUserModal.cancel')}
          </Button>
          <Button onClick={onSubmit} disabled={isCreating}>
            {isCreating ? t('settings.createUserModal.creating') : t('settings.createUserModal.createUser')}
          </Button>
        </div>
      </div>
    </div>
  )
}
