import { useState, useMemo, useEffect } from 'react'
import { Users, UserPlus, RefreshCw, Shield, UserCog, User, Edit, Key, ToggleRight, ToggleLeft, RotateCcw, Trash2, CheckSquare, Square, AlertTriangle, Construction, Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Select } from '../ui/select'
import { UserListItem } from '../../api'

export interface UsersTabProps {
  users: UserListItem[]
  loadingUsers: boolean
  usersError: string | null
  currentUserId: string | undefined
  maintenanceMode: boolean
  onShowCreateUser: () => void
  onLoadUsers: () => void
  onEditUser: (user: UserListItem) => void
  onOpenPermissionModal: (user: UserListItem) => void
  onToggleUserActive: (user: UserListItem) => void
  onRevokeAgreement: (userId: string) => void
  onDeleteUser: (userId: string) => void
  onBatchActivate: (userIds: string[]) => void
  onBatchDeactivate: (userIds: string[]) => void
  onBatchDelete: (userIds: string[]) => void
  onToggleMaintenanceMode: () => void
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
  maintenanceMode,
  onShowCreateUser,
  onLoadUsers,
  onEditUser,
  onOpenPermissionModal,
  onToggleUserActive,
  onRevokeAgreement,
  onDeleteUser,
  onBatchActivate,
  onBatchDeactivate,
  onBatchDelete,
  onToggleMaintenanceMode
}: UsersTabProps) {
  // Batch selection state
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(new Set())

  // Search and Pagination State
  const [searchQuery, setSearchQuery] = useState('')
  const [itemsPerPage, setItemsPerPage] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)

  // Reset page when search or items per page changes
  useEffect(() => {
    setCurrentPage(1)
  }, [searchQuery, itemsPerPage])

  // Filtered users
  const filteredUsers = useMemo(() => {
    if (!searchQuery.trim()) return users
    const query = searchQuery.toLowerCase()
    return users.filter(user => 
      user.email.toLowerCase().includes(query) || 
      (user.nickname && user.nickname.toLowerCase().includes(query))
    )
  }, [users, searchQuery])

  // Paginated users
  const paginatedUsers = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage
    return filteredUsers.slice(start, start + itemsPerPage)
  }, [filteredUsers, currentPage, itemsPerPage])

  const totalPages = Math.ceil((filteredUsers.length || 1) / itemsPerPage)

  // Users that can be batch selected (not admin, not current user) - from current page
  const selectableUsers = useMemo(() => {
    return paginatedUsers.filter(user => user.role !== 'admin' && user.id !== currentUserId)
  }, [paginatedUsers, currentUserId])

  const allSelectableSelected = selectableUsers.length > 0 && selectableUsers.every(u => selectedUserIds.has(u.id))
  const someSelected = selectedUserIds.size > 0

  // Check if a user can be batch selected
  const canSelectUser = (user: UserListItem) => {
    return user.role !== 'admin' && user.id !== currentUserId
  }

  const toggleSelectAll = () => {
    if (allSelectableSelected) {
      // Deselect current page items
      const newSet = new Set(selectedUserIds)
      selectableUsers.forEach(u => newSet.delete(u.id))
      setSelectedUserIds(newSet)
    } else {
      // Select current page items
      const newSet = new Set(selectedUserIds)
      selectableUsers.forEach(u => newSet.add(u.id))
      setSelectedUserIds(newSet)
    }
  }

  const toggleSelectUser = (userId: string) => {
    const newSet = new Set(selectedUserIds)
    if (newSet.has(userId)) {
      newSet.delete(userId)
    } else {
      newSet.add(userId)
    }
    setSelectedUserIds(newSet)
  }

  const handleBatchActivate = () => {
    onBatchActivate(Array.from(selectedUserIds))
    setSelectedUserIds(new Set())
  }

  const handleBatchDeactivate = () => {
    onBatchDeactivate(Array.from(selectedUserIds))
    setSelectedUserIds(new Set())
  }

  const handleBatchDelete = () => {
    onBatchDelete(Array.from(selectedUserIds))
    setSelectedUserIds(new Set())
  }

  return (
    <Card className="p-4 sm:p-6">
      {/* Maintenance Mode Banner */}
      {maintenanceMode && (
        <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg flex items-center gap-3">
          <Construction className="w-5 h-5 text-amber-600 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-amber-800 font-medium">Maintenance Mode Active</p>
            <p className="text-amber-600 text-sm">Non-admin users cannot log in. All non-admin users are temporarily deactivated.</p>
          </div>
        </div>
      )}

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
          <Users className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 flex-shrink-0" />
          User Management
        </h2>
        <div className="flex flex-wrap gap-2 self-end sm:self-auto items-center">
          <div className="relative w-full sm:w-64 mr-2">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" />
            <Input 
              placeholder="Search user..." 
              className="pl-9 h-9"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          {/* Maintenance Mode Toggle */}
          <Button
            variant={maintenanceMode ? "destructive" : "outline"}
            onClick={onToggleMaintenanceMode}
            className="gap-2"
            title={maintenanceMode ? "Disable maintenance mode" : "Enable maintenance mode"}
          >
            <Construction className="w-4 h-4" />
            {maintenanceMode ? "End Maintenance Mode" : "Maintenance Mode"}
          </Button>
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

      {/* Batch Actions Bar */}
      {someSelected && (
        <div className="mb-4 p-3 bg-primary-50 border border-primary-200 rounded-lg flex flex-wrap items-center gap-3">
          <span className="text-primary-800 font-medium text-sm">
            {selectedUserIds.size} user{selectedUserIds.size > 1 ? 's' : ''} selected
          </span>
          <div className="flex gap-2 ml-auto">
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchActivate}
              className="gap-1 text-emerald-600 border-emerald-300 hover:bg-emerald-50"
            >
              <ToggleRight className="w-4 h-4" />
              Activate
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchDeactivate}
              className="gap-1 text-gray-600 border-gray-300 hover:bg-gray-100"
            >
              <ToggleLeft className="w-4 h-4" />
              Deactivate
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchDelete}
              className="gap-1 text-red-600 border-red-300 hover:bg-red-50"
            >
              <Trash2 className="w-4 h-4" />
              Delete
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedUserIds(new Set())}
              className="text-gray-500"
            >
              Clear
            </Button>
          </div>
        </div>
      )}

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
        <>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="w-10 py-3 px-2">
                  <button
                    onClick={toggleSelectAll}
                    className="p-1 rounded hover:bg-gray-100 transition-colors"
                    title={allSelectableSelected ? "Deselect all" : "Select all"}
                    disabled={selectableUsers.length === 0}
                  >
                    {allSelectableSelected && selectableUsers.length > 0 ? (
                      <CheckSquare className="w-4 h-4 text-primary-600" />
                    ) : (
                      <Square className="w-4 h-4 text-gray-400" />
                    )}
                  </button>
                </th>
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
              {paginatedUsers.map((user) => {
                const isSelectable = canSelectUser(user)
                const isSelected = selectedUserIds.has(user.id)
                return (
                  <tr key={user.id} className={`border-b border-gray-100 hover:bg-gray-50 ${isSelected ? 'bg-primary-50' : ''}`}>
                    <td className="py-3 px-2">
                      {isSelectable ? (
                        <button
                          onClick={() => toggleSelectUser(user.id)}
                          className="p-1 rounded hover:bg-gray-100 transition-colors"
                        >
                          {isSelected ? (
                            <CheckSquare className="w-4 h-4 text-primary-600" />
                          ) : (
                            <Square className="w-4 h-4 text-gray-400" />
                          )}
                        </button>
                      ) : (
                        <div className="p-1 opacity-30" title="Admin and current user cannot be batch selected">
                          <Square className="w-4 h-4 text-gray-300" />
                        </div>
                      )}
                    </td>
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
                )
              })}
              {filteredUsers.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-gray-500">
                    {searchQuery ? 'No users matching search' : 'No users found'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {!loadingUsers && filteredUsers.length > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mt-4 px-2">
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <span className="whitespace-nowrap">Rows per page:</span>
              <div className="w-[70px]">
                <Select
                  value={itemsPerPage.toString()}
                  onChange={(v) => setItemsPerPage(Number(v))}
                  options={[
                    { value: '5', label: '5' },
                    { value: '10', label: '10' },
                    { value: '20', label: '20' }
                  ]}
                  className="h-8"
                />
              </div>
              <span className="hidden sm:inline text-gray-300">|</span>
              <span className="whitespace-nowrap">
                Page {currentPage} of {totalPages || 1}
              </span>
              <span className="text-gray-400 whitespace-nowrap hidden sm:inline">({filteredUsers.length} total)</span>
            </div>
            
            <div className="flex items-center gap-2">
              <Button
                variant="outline" 
                size="sm"
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="h-8 w-8 p-0"
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages || totalPages === 0}
                className="h-8 w-8 p-0"
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        )}
        </>
      )}
    </Card>
  )
}

