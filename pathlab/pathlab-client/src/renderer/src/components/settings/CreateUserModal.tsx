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
}

export function CreateUserModal({ createForm, onCreateFormChange, onSubmit, onClose, isCreating }: CreateUserModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <UserPlus className="w-5 h-5 mr-2 text-primary-600" />
          Create New User
        </h3>
        <div className="space-y-4">
          <div>
            <Label className="text-sm text-gray-600">Username *</Label>
            <Input
              value={createForm.username}
              onChange={(e) => onCreateFormChange({ ...createForm, username: e.target.value })}
              className="mt-1"
              placeholder="Enter username"
              disabled={isCreating}
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">Password *</Label>
            <Input
              type="password"
              value={createForm.password}
              onChange={(e) => onCreateFormChange({ ...createForm, password: e.target.value })}
              className="mt-1"
              placeholder="Minimum 6 characters"
              disabled={isCreating}
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">Nickname</Label>
            <Input
              value={createForm.nickname}
              onChange={(e) => onCreateFormChange({ ...createForm, nickname: e.target.value })}
              className="mt-1"
              placeholder="Display name (optional)"
              disabled={isCreating}
            />
          </div>
          <div>
            <Label className="text-sm text-gray-600">Role</Label>
            <select
              value={createForm.role}
              onChange={(e) => onCreateFormChange({ ...createForm, role: e.target.value })}
              className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              disabled={isCreating}
            >
              <option value="admin">Admin</option>
              <option value="pathologist">Pathologist</option>
              <option value="guest">Guest</option>
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="outline" onClick={onClose} disabled={isCreating}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={isCreating}>
            {isCreating ? 'Creating...' : 'Create User'}
          </Button>
        </div>
      </div>
    </div>
  )
}

