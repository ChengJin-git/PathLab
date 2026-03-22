import { useTranslation } from 'react-i18next'
import { UserPlus } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'

export interface CreateUserModalProps {
  createForm: { username: string; password: string; nickname: string; role: string; registration_email: string }
  onCreateFormChange: (form: { username: string; password: string; nickname: string; role: string; registration_email: string }) => void
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
            <Label className="text-sm text-gray-600">{t('settings.createUserModal.email')}</Label>
            <Input
              value={createForm.registration_email}
              onChange={(e) => onCreateFormChange({ ...createForm, registration_email: e.target.value })}
              className="mt-1"
              placeholder={t('settings.createUserModal.emailPlaceholder')}
              disabled={isCreating}
              type="email"
            />
          </div>
           <div>
             <Label className="text-sm text-gray-600">{t('settings.createUserModal.role')}</Label>
             <Select
               value={createForm.role}
               onChange={(v) => onCreateFormChange({ ...createForm, role: v })}
               options={[
                 { value: 'admin', label: t('settings.createUserModal.roleAdmin') },
                 { value: 'pathologist', label: t('settings.createUserModal.rolePathologist') },
                 { value: 'guest', label: t('settings.createUserModal.roleGuest') },
               ]}
               disabled={isCreating}
             />
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
