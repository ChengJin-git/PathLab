import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { UserListItem } from '../../api'

export interface EditUserModalProps {
  user: UserListItem
  editForm: { nickname: string; role: string; password: string }
  onEditFormChange: (form: { nickname: string; role: string; password: string }) => void
  onSave: () => void
  onClose: () => void
}

export function EditUserModal({ user, editForm, onEditFormChange, onSave, onClose }: EditUserModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Edit User</h3>
        <div className="space-y-4">
          <div>
            <Label className="text-sm text-gray-600">Username</Label>
            <Input value={user.email} disabled className="mt-1 bg-gray-50" />
          </div>
          <div>
            <Label className="text-sm text-gray-600">Nickname</Label>
            <Input
              value={editForm.nickname}
              onChange={(e) => onEditFormChange({ ...editForm, nickname: e.target.value })}
              className="mt-1"
              placeholder="Enter nickname"
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">New Password</Label>
            <Input
              type="password"
              value={editForm.password}
              onChange={(e) => onEditFormChange({ ...editForm, password: e.target.value })}
              className="mt-1"
              placeholder="Leave empty to keep current password"
            />
            <p className="text-xs text-gray-400 mt-1">Minimum 6 characters. Leave empty to keep current password.</p>
          </div>
          <div>
            <Label className="text-sm text-gray-600">Role</Label>
            <select
              value={editForm.role}
              onChange={(e) => onEditFormChange({ ...editForm, role: e.target.value })}
              className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="admin">Admin</option>
              <option value="pathologist">Pathologist</option>
              <option value="guest">Guest</option>
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSave}>
            Save Changes
          </Button>
        </div>
      </div>
    </div>
  )
}

