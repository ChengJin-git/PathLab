import { Users, UserPlus, RefreshCw, Shield, UserCog, User, Edit, Key, ToggleRight, ToggleLeft, RotateCcw, Trash2 } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { UserListItem } from '../../api'

export interface UsersTabProps {
  users: UserListItem[]
  loadingUsers: boolean
  usersError: string | null
  currentUserId: string | undefined
  onShowCreateUser: () => void
  onLoadUsers: () => void
  onEditUser: (user: UserListItem) => void
  onOpenPermissionModal: (user: UserListItem) => void
  onToggleUserActive: (user: UserListItem) => void
  onRevokeAgreement: (userId: string) => void
  onDeleteUser: (userId: string) => void
}

function getRoleBadgeColor(role: string) {
  switch (role) {
    case 'admin': return 'bg-red-100 text-red-800 border-red-200'
    case 'pathologist': return 'bg-primary-100 text-primary-800 border-primary-200'
    case 'guest': return 'bg-gray-100 text-gray-800 border-gray-200'
    default: return 'bg-gray-100 text-gray-800 border-gray-200'
  }
}

export function UsersTab({
  users,
  loadingUsers,
  usersError,
  currentUserId,
  onShowCreateUser,
  onLoadUsers,
  onEditUser,
  onOpenPermissionModal,
  onToggleUserActive,
  onRevokeAgreement,
  onDeleteUser
}: UsersTabProps) {
  return (
    <Card className="p-4 sm:p-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
          <Users className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
          User Management
        </h2>
        <div className="flex gap-2 self-end sm:self-auto">
          <Button onClick={onShowCreateUser} className="gap-2">
            <UserPlus className="w-4 h-4" />
            Create User
          </Button>
          <Button variant="outline" onClick={onLoadUsers} disabled={loadingUsers} className="gap-2">
            <RefreshCw className={`w-4 h-4 ${loadingUsers ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {usersError && (
        <div className="mb-4 p-4 bg-red-100 border border-red-300 rounded-lg text-red-600 text-sm">
          {usersError}
        </div>
      )}

      {loadingUsers ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-3 px-4 font-medium text-gray-600">Username</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600">Nickname</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600">Role</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600">Status</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600">Agreement</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600">Consent IP</th>
                <th className="text-right py-3 px-4 font-medium text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-3 px-4 text-gray-900">{user.email}</td>
                  <td className="py-3 px-4 text-gray-600">{user.nickname || '-'}</td>
                  <td className="py-3 px-4">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${getRoleBadgeColor(user.role)}`}>
                      {user.role === 'admin' && <Shield className="w-3 h-3 mr-1" />}
                      {user.role === 'pathologist' && <UserCog className="w-3 h-3 mr-1" />}
                      {user.role === 'guest' && <User className="w-3 h-3 mr-1" />}
                      {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
                    </span>
                  </td>
                  <td className="py-3 px-4">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="py-3 px-4">
                    {user.role === 'admin' ? (
                      <span className="text-xs text-gray-500 italic">Auto accepted</span>
                    ) : user.agreement_accepted_at ? (
                      <span className="text-xs text-green-600">
                        {new Date(user.agreement_accepted_at).toLocaleDateString()}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">Not accepted</span>
                    )}
                  </td>
                  <td className="py-3 px-4">
                    {user.role === 'admin' ? (
                      <span className="text-xs text-gray-500 italic">-</span>
                    ) : user.agreement_ip ? (
                      <span className="text-xs text-gray-600">{user.agreement_ip}</span>
                    ) : (
                      <span className="text-xs text-gray-400">-</span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button variant="ghost" size="sm" onClick={() => onEditUser(user)} className="h-8 w-8 p-0" title="Edit user">
                        <Edit className="w-4 h-4" />
                      </Button>
                      {user.role !== 'admin' && (
                        <Button variant="ghost" size="sm" onClick={() => onOpenPermissionModal(user)} className="h-8 w-8 p-0 text-purple-600 hover:text-purple-700 hover:bg-purple-50" title="Manage dataset permissions">
                          <Key className="w-4 h-4" />
                        </Button>
                      )}
                      {(!currentUserId || user.id !== currentUserId) && user.email !== 'admin' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onToggleUserActive(user)}
                          className={`h-8 w-8 p-0 ${user.is_active ? 'text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'}`}
                          title={user.is_active ? 'Deactivate user' : 'Activate user'}
                        >
                          {user.is_active ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
                        </Button>
                      )}
                      {user.agreement_accepted_at && (
                        <Button variant="ghost" size="sm" onClick={() => onRevokeAgreement(user.id)} className="h-8 w-8 p-0 text-orange-600 hover:text-orange-700 hover:bg-orange-50" title="Revoke agreement">
                          <RotateCcw className="w-4 h-4" />
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" onClick={() => onDeleteUser(user.id)} className="h-8 w-8 p-0 text-red-600 hover:text-red-700 hover:bg-red-50" title="Delete user">
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-gray-500">
                    No users found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

