import { useTranslation } from 'react-i18next'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import type { UserListItem } from '../../api/users'
import { ModalShell } from '../ui/modal-shell'

export interface EditUserModalProps {
  user: UserListItem
  editForm: { nickname: string; role: string; password: string; registration_email: string }
  onEditFormChange: (form: { nickname: string; role: string; password: string; registration_email: string }) => void
  onSave: () => void
  onClose: () => void
}

export function EditUserModal({ user, editForm, onEditFormChange, onSave, onClose }: EditUserModalProps) {
  const { t } = useTranslation()

  return (
    <ModalShell isOpen={true} onClose={onClose} maxWidth="md" className="p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('settings.editUserModal.title')}</h3>
        <div className="space-y-4">
          <div>
            <Label className="text-sm text-gray-600">{t('settings.editUserModal.username')}</Label>
            <Input value={user.username} disabled className="mt-1 bg-gray-50" />
          </div>
          <div>
            <Label className="text-sm text-gray-600">{t('settings.editUserModal.nickname')}</Label>
            <Input
              value={editForm.nickname}
              onChange={(e) => onEditFormChange({ ...editForm, nickname: e.target.value })}
              className="mt-1"
              placeholder={t('settings.editUserModal.enterNickname')}
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">{t('settings.editUserModal.email')}</Label>
            <Input
              value={editForm.registration_email}
              onChange={(e) => onEditFormChange({ ...editForm, registration_email: e.target.value })}
              className="mt-1"
              placeholder={t('settings.editUserModal.emailPlaceholder')}
              type="email"
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">{t('settings.editUserModal.newPassword')}</Label>
            <Input
              type="password"
              value={editForm.password}
              onChange={(e) => onEditFormChange({ ...editForm, password: e.target.value })}
              className="mt-1"
              placeholder={t('settings.editUserModal.leaveEmptyToKeep')}
            />
            <p className="text-xs text-gray-400 mt-1">{t('settings.editUserModal.passwordHint')}</p>
          </div>
           <div>
             <Label className="text-sm text-gray-600">{t('settings.editUserModal.role')}</Label>
             <Select
               value={editForm.role}
               onChange={(v) => onEditFormChange({ ...editForm, role: v })}
               options={[
                 { value: 'admin', label: t('settings.editUserModal.roleAdmin') },
                 { value: 'pathologist', label: t('settings.editUserModal.rolePathologist') },
                 { value: 'guest', label: t('settings.editUserModal.roleGuest') },
               ]}
             />
           </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="outline" onClick={onClose}>
            {t('settings.editUserModal.cancel')}
          </Button>
          <Button onClick={onSave}>
            {t('settings.editUserModal.saveChanges')}
          </Button>
        </div>
    </ModalShell>
  )
}
