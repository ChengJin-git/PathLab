import { useState, useMemo, useEffect, useCallback } from 'react'
import { useAsyncAction } from '../../lib/hooks/useAsyncAction'
import { useTranslation } from 'react-i18next'
import { Users, UserPlus, RefreshCw, Shield, UserCog, User, Edit, ToggleRight, ToggleLeft, RotateCcw, Trash2, CheckSquare, Square, Construction, Search } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Tooltip } from '../ui/tooltip'
import { Input } from '../ui/input'
import { Select } from '../ui/select'
import {
  listUsersPaged, createUser, updateUser, deleteUser, revokeUserAgreement,
  batchActivateUsers, batchDeactivateUsers, batchDeleteUsers,
  getMaintenanceMode, setMaintenanceMode as setMaintenanceModeApi,
} from '../../api/users'
import type { UserListItem } from '../../api/users'
import type { AdminUserUpdateRequest } from '../../api/auth'
import { ShowConfirmDialog } from './ConfirmDialog'
import { EditUserModal } from './EditUserModal'
import { CreateUserModal } from './CreateUserModal'
import { AnnotationAuditCard } from './AnnotationAuditCard'
import { PaginationFooter } from '../ui/pagination-footer'
import { useAuth } from '../../contexts/AuthContext'

export interface UsersTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
  currentUserId: string | undefined
}

function getRoleBadgeColor(role: string) {
  switch (role) {
    case 'admin': return 'bg-red-100 text-red-800 border-red-200'
    case 'pathologist': return 'bg-primary-100 text-primary-800 border-primary-200'
    case 'guest': return 'bg-gray-100 text-gray-800 border-gray-200'
    default: return 'bg-gray-100 text-gray-800 border-gray-200'
  }
}

export function UsersTab({ showConfirmDialog, closeConfirmDialog, currentUserId }: UsersTabProps) {
  const { t } = useTranslation()
  const { isAdmin } = useAuth()

  // User management state
  const [users, setUsers] = useState<UserListItem[]>([])
  const [loadingUsers, setLoadingUsers] = useState(false)
  const [usersError, setUsersError] = useState<string | null>(null)
  const [editingUser, setEditingUser] = useState<UserListItem | null>(null)
  const [editForm, setEditForm] = useState<{ nickname: string; role: string; password: string; registration_email: string }>({ nickname: '', role: '', password: '', registration_email: '' })
  const [showCreateUser, setShowCreateUser] = useState(false)
  const [createForm, setCreateForm] = useState<{ username: string; password: string; nickname: string; role: string; registration_email: string }>({ username: '', password: '', nickname: '', role: 'pathologist', registration_email: '' })
  const [creatingUser, runCreatingUser] = useAsyncAction<void>({ onError: (err) => setUsersError(err instanceof Error ? err.message : t('settings.usersTab.failedToCreateUser')) })
  const [maintenanceMode, setMaintenanceMode] = useState(false)


  // Batch selection state
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(new Set())

  // Search and Pagination State
  const [searchQuery, setSearchQuery] = useState('')
  const [itemsPerPage, setItemsPerPage] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalUsers, setTotalUsers] = useState(0)

  // --- Data loading ---
  const loadUsers = useCallback(async () => {
    setLoadingUsers(true)
    setUsersError(null)
    try {
      const response = await listUsersPaged({
        page: currentPage,
        page_size: itemsPerPage,
        search: searchQuery.trim() || undefined
      })

      const nextTotalPages = Math.max(1, Math.ceil(response.total / itemsPerPage) || 1)
      if (response.total > 0 && currentPage > nextTotalPages) {
        setCurrentPage(nextTotalPages)
        return
      }

      setUsers(response.items)
      setTotalUsers(response.total)
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : t('settings.usersTab.failedToLoadUsers'))
    } finally {
      setLoadingUsers(false)
    }
  }, [currentPage, itemsPerPage, searchQuery, t])

  const loadMaintenanceMode = useCallback(async () => {
    try {
      const result = await getMaintenanceMode()
      setMaintenanceMode(result.enabled)
    } catch (err) {
      console.error('Failed to load maintenance mode:', err)
    }
  }, [])

  useEffect(() => {
    loadUsers()
    loadMaintenanceMode()
  }, [loadUsers, loadMaintenanceMode])

  // --- User CRUD handlers ---
  const handleSaveUser = async () => {
    if (!editingUser) return
    if (editForm.password && editForm.password.length < 6) {
      setUsersError(t('settings.usersTab.passwordMinLength'))
      return
    }
    try {
      const updateData: AdminUserUpdateRequest = {}
      if (editForm.nickname !== (editingUser.nickname || '')) updateData.nickname = editForm.nickname
      if (editForm.role !== editingUser.role) updateData.role = editForm.role as 'admin' | 'pathologist' | 'guest'
      if (editForm.password) updateData.password = editForm.password
      if (editForm.registration_email !== (editingUser.registration_email || '')) updateData.registration_email = editForm.registration_email || undefined
      await updateUser(editingUser.id, updateData)
      setEditingUser(null)
      setUsersError(null)
      loadUsers()
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : t('settings.usersTab.failedToUpdateUser'))
    }
  }

  const handleCreateUser = () => {
    if (!createForm.username || !createForm.password) { setUsersError(t('settings.usersTab.usernamePasswordRequired')); return }
    if (createForm.password.length < 6) { setUsersError(t('settings.usersTab.passwordMinLength')); return }
    setUsersError(null)
    void runCreatingUser(async () => {
      await createUser({
        username: createForm.username,
        password: createForm.password,
        nickname: createForm.nickname || undefined,
        role: createForm.role as 'admin' | 'pathologist' | 'guest',
        registration_email: createForm.registration_email || undefined,
      })
      setShowCreateUser(false)
      setCreateForm({ username: '', password: '', nickname: '', role: 'pathologist', registration_email: '' })
      loadUsers()
    })
  }

  const handleToggleUserActive = async (user: UserListItem) => {
    try {
      await updateUser(user.id, { is_active: !user.is_active })
      loadUsers()
    } catch { /* Error handled */ }
  }

  const handleRevokeAgreement = async (userId: string) => {
    try {
      await revokeUserAgreement(userId)
      loadUsers()
    } catch { /* Error handled */ }
  }

  const handleDeleteUser = (userId: string) => {
    showConfirmDialog({
      title: t('settings.usersTab.deleteUser'),
      message: t('settings.usersTab.deleteUserConfirm'),
      confirmVariant: 'danger',
      confirmText: t('settings.usersTab.delete'),
      onConfirm: async () => {
        try {
          await deleteUser(userId)
          loadUsers()
        } catch { /* Error handled */ }
        closeConfirmDialog()
      }
    })
  }

  const totalPages = Math.max(1, Math.ceil(totalUsers / itemsPerPage) || 1)

  // Users that can be batch selected (not admin, not current user) - from current page
  const selectableUsers = useMemo(() => {
    return users.filter(user => user.role !== 'admin' && user.id !== currentUserId)
  }, [users, currentUserId])

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
      selectableUsers.forEach(u => {
        newSet.delete(u.id)
      })
      setSelectedUserIds(newSet)
    } else {
      // Select current page items
      const newSet = new Set(selectedUserIds)
      selectableUsers.forEach(u => {
        newSet.add(u.id)
      })
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

  const handleBatchActivate = async () => {
    const ids = Array.from(selectedUserIds)
    if (ids.length === 0) return
    try { await batchActivateUsers(ids); loadUsers() }
    catch (err) { setUsersError(err instanceof Error ? err.message : t('settings.usersTab.failedToBatchActivate')) }
    setSelectedUserIds(new Set())
  }

  const handleBatchDeactivate = async () => {
    const ids = Array.from(selectedUserIds)
    if (ids.length === 0) return
    try { await batchDeactivateUsers(ids); loadUsers() }
    catch (err) { setUsersError(err instanceof Error ? err.message : t('settings.usersTab.failedToBatchDeactivate')) }
    setSelectedUserIds(new Set())
  }

  const handleBatchDelete = () => {
    const ids = Array.from(selectedUserIds)
    if (ids.length === 0) return
    showConfirmDialog({
      title: t('settings.usersTab.deleteUsers'),
      message: t('settings.usersTab.deleteUsersConfirm', { count: ids.length }),
      confirmVariant: 'danger',
      confirmText: t('settings.usersTab.delete'),
      onConfirm: async () => {
        try { await batchDeleteUsers(ids); loadUsers() }
        catch (err) { setUsersError(err instanceof Error ? err.message : t('settings.usersTab.failedToBatchDelete')) }
        closeConfirmDialog()
      }
    })
    setSelectedUserIds(new Set())
  }

  const handleToggleMaintenanceMode = () => {
    const newMode = !maintenanceMode
    const title = newMode ? t('settings.usersTab.enableMaintenanceMode') : t('settings.usersTab.disableMaintenanceMode')
    const message = newMode
      ? t('settings.usersTab.enableMaintenanceConfirm')
      : t('settings.usersTab.disableMaintenanceConfirm')
    showConfirmDialog({
      title, message,
      confirmVariant: newMode ? 'danger' : 'info',
      confirmText: newMode ? t('settings.usersTab.enable') : t('settings.usersTab.disable'),
      onConfirm: async () => {
        try {
          const result = await setMaintenanceModeApi(newMode)
          setMaintenanceMode(result.enabled)
          loadUsers()
        } catch (err) {
          setUsersError(err instanceof Error ? err.message : t('settings.usersTab.failedToToggleMaintenance'))
        }
        closeConfirmDialog()
      }
    })
  }

  return (
    <>
    <Card className="p-4 sm:p-6">
      {/* Maintenance Mode Banner */}
      {maintenanceMode && (
        <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg flex items-center gap-3">
          <Construction className="w-5 h-5 text-amber-600 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-amber-800 font-medium">{t('settings.usersTab.maintenanceModeActive')}</p>
            <p className="text-amber-600 text-sm">{t('settings.usersTab.maintenanceModeDescription')}</p>
          </div>
        </div>
      )}

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
          <Users className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 flex-shrink-0" />
          {t('settings.usersTab.title')}
        </h2>
        <div className="flex flex-wrap gap-2 self-end sm:self-auto items-center">
          <div className="relative w-full sm:w-64 mr-2">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" />
            <Input 
              placeholder={t('settings.usersTab.searchPlaceholder')} 
              className="pl-9 h-9"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
                setCurrentPage(1)
              }}
            />
          </div>
          {/* Maintenance Mode Toggle */}
          <Tooltip content={maintenanceMode ? t('settings.usersTab.disableMaintenanceModeTitle') : t('settings.usersTab.enableMaintenanceModeTitle')}>
            <Button
              variant={maintenanceMode ? "destructive" : "outline"}
              onClick={handleToggleMaintenanceMode}
              className="gap-2"
            >
              <Construction className="w-4 h-4" />
              <span className="hidden sm:inline">{maintenanceMode ? t('settings.usersTab.endMaintenanceMode') : t('settings.usersTab.maintenanceMode')}</span>
            </Button>
          </Tooltip>
          <Button onClick={() => setShowCreateUser(true)} className="gap-2">
            <UserPlus className="w-4 h-4" />
            <span className="hidden sm:inline">{t('settings.usersTab.createUser')}</span>
          </Button>
          <Button variant="outline" onClick={loadUsers} disabled={loadingUsers} className="gap-2">
            <RefreshCw className={`w-4 h-4 ${loadingUsers ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">{t('settings.usersTab.refresh')}</span>
          </Button>
        </div>
      </div>

      {/* Batch Actions Bar */}
      {someSelected && (
        <div className="mb-4 p-3 bg-primary-50 border border-primary-200 rounded-lg flex flex-wrap items-center gap-3">
          <span className="text-primary-800 font-medium text-sm">
            {t('settings.usersTab.usersSelected', { count: selectedUserIds.size })}
          </span>
          <div className="flex gap-2 ml-auto">
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchActivate}
              className="gap-1 text-emerald-600 border-emerald-300 hover:bg-emerald-50"
            >
              <ToggleRight className="w-4 h-4" />
              {t('settings.usersTab.activate')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchDeactivate}
              className="gap-1 text-gray-600 border-gray-300 hover:bg-gray-100"
            >
              <ToggleLeft className="w-4 h-4" />
              {t('settings.usersTab.deactivate')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchDelete}
              className="gap-1 text-red-600 border-red-300 hover:bg-red-50"
            >
              <Trash2 className="w-4 h-4" />
              {t('settings.usersTab.delete')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedUserIds(new Set())}
              className="text-gray-500"
            >
              {t('settings.usersTab.clear')}
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
                  <Tooltip content={allSelectableSelected ? t('settings.usersTab.deselectAll') : t('settings.usersTab.selectAll')}>
                    <button
                      type="button"
                      onClick={toggleSelectAll}
                      className="p-1 rounded hover:bg-gray-100 transition-colors"
                      disabled={selectableUsers.length === 0}
                    >
                      {allSelectableSelected && selectableUsers.length > 0 ? (
                        <CheckSquare className="w-4 h-4 text-primary-600" />
                      ) : (
                        <Square className="w-4 h-4 text-gray-400" />
                      )}
                    </button>
                  </Tooltip>
                </th>
                <th className="text-left py-3 px-2 sm:px-4 font-medium text-gray-600">{t('settings.usersTab.columnUsername')}</th>
                <th className="text-left py-3 px-2 sm:px-4 font-medium text-gray-600 hidden xs:table-cell sm:table-cell">{t('settings.usersTab.columnNickname')}</th>
                <th className="text-left py-3 px-2 sm:px-4 font-medium text-gray-600">{t('settings.usersTab.columnRole')}</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600 hidden sm:table-cell">{t('settings.usersTab.columnStatus')}</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600 hidden md:table-cell">{t('settings.usersTab.columnEmail')}</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600 hidden md:table-cell">{t('settings.usersTab.columnAgreement')}</th>
                <th className="text-left py-3 px-4 font-medium text-gray-600 hidden lg:table-cell">{t('settings.usersTab.columnConsentIP')}</th>
                <th className="text-right py-3 px-2 sm:px-4 font-medium text-gray-600">{t('settings.usersTab.columnActions')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const isSelectable = canSelectUser(user)
                const isSelected = selectedUserIds.has(user.id)
                return (
                  <tr key={user.id} className={`border-b border-gray-100 hover:bg-gray-50 ${isSelected ? 'bg-primary-50' : ''}`}>
                    <td className="py-3 px-2">
                      {isSelectable ? (
                        <button
                          type="button"
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
                        <div className="p-1 opacity-30" title={t('settings.usersTab.cannotBatchSelect')}>
                          <Square className="w-4 h-4 text-gray-300" />
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-2 sm:px-4 text-gray-900 text-xs sm:text-sm">{user.username}</td>
                    <td className="py-3 px-2 sm:px-4 text-gray-600 text-xs sm:text-sm hidden xs:table-cell sm:table-cell">{user.nickname || '-'}</td>
                    <td className="py-3 px-2 sm:px-4">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap ${getRoleBadgeColor(user.role)}`}>
                        {user.role === 'admin' && <Shield className="w-3 h-3 mr-1 flex-shrink-0" />}
                        {user.role === 'pathologist' && <UserCog className="w-3 h-3 mr-1 flex-shrink-0" />}
                        {user.role === 'guest' && <User className="w-3 h-3 mr-1 flex-shrink-0" />}
                        {t(`settings.usersTab.role_${user.role}`)}
                      </span>
                    </td>
                    <td className="py-3 px-4 hidden sm:table-cell">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                        {user.is_active ? t('settings.usersTab.active') : t('settings.usersTab.inactive')}
                      </span>
                    </td>
                    <td className="py-3 px-4 hidden md:table-cell">
                      {user.registration_email ? (
                        <Tooltip content={t('settings.usersTab.editUser')}>
                          <button
                            type="button"
                            onClick={() => { setEditingUser(user); setEditForm({ nickname: user.nickname || '', role: user.role, password: '', registration_email: user.registration_email || '' }) }}
                            className="text-xs text-blue-600 font-mono hover:underline cursor-pointer"
                          >
                            {user.registration_email}
                          </button>
                        </Tooltip>
                      ) : (
                        <Tooltip content={t('settings.usersTab.editUser')}>
                          <button
                            type="button"
                            onClick={() => { setEditingUser(user); setEditForm({ nickname: user.nickname || '', role: user.role, password: '', registration_email: '' }) }}
                            className="text-xs text-gray-400 hover:text-blue-600 hover:underline cursor-pointer"
                          >
                            -
                          </button>
                        </Tooltip>
                      )}
                    </td>
                    <td className="py-3 px-4 hidden md:table-cell">
                      {user.role === 'admin' ? (
                        <span className="text-xs text-gray-500 italic">{t('settings.usersTab.autoAccepted')}</span>
                      ) : user.agreement_accepted_at ? (
                        <span className="text-xs text-green-600">
                          {new Date(user.agreement_accepted_at).toLocaleDateString()}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">{t('settings.usersTab.notAccepted')}</span>
                      )}
                    </td>
                    <td className="py-3 px-4 hidden lg:table-cell">
                      {user.role === 'admin' ? (
                        <span className="text-xs text-gray-500 italic">-</span>
                      ) : user.agreement_ip ? (
                        <span className="text-xs text-gray-600">{user.agreement_ip}</span>
                      ) : (
                        <span className="text-xs text-gray-400">-</span>
                      )}
                    </td>
                    <td className="py-3 px-2 sm:px-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Tooltip content={t('settings.usersTab.editUser')}>
                          <Button variant="ghost" size="sm" onClick={() => { setEditingUser(user); setEditForm({ nickname: user.nickname || '', role: user.role, password: '', registration_email: user.registration_email || '' }) }} className="h-8 w-8 p-0">
                            <Edit className="w-4 h-4" />
                          </Button>
                        </Tooltip>
                        {(!currentUserId || user.id !== currentUserId) && user.username !== 'admin' && (
                          <Tooltip content={user.is_active ? t('settings.usersTab.deactivateUser') : t('settings.usersTab.activateUser')}>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleToggleUserActive(user)}
                              className={`h-8 w-8 p-0 ${user.is_active ? 'text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'}`}
                            >
                              {user.is_active ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
                            </Button>
                          </Tooltip>
                        )}
                        {user.agreement_accepted_at && (
                          <Tooltip content={t('settings.usersTab.revokeAgreement')}>
                            <Button variant="ghost" size="sm" onClick={() => handleRevokeAgreement(user.id)} className="h-8 w-8 p-0 text-orange-600 hover:text-orange-700 hover:bg-orange-50">
                              <RotateCcw className="w-4 h-4" />
                            </Button>
                          </Tooltip>
                        )}
                        <Tooltip content={t('settings.usersTab.deleteUserAction')}>
                          <Button variant="ghost" size="sm" onClick={() => handleDeleteUser(user.id)} className="h-8 w-8 p-0 text-red-600 hover:text-red-700 hover:bg-red-50">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </Tooltip>
                      </div>
                    </td>
                  </tr>
                )
              })}
              {users.length === 0 && (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-gray-500">
                    {searchQuery ? t('settings.usersTab.noUsersMatchingSearch') : t('settings.usersTab.noUsersFound')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {!loadingUsers && totalUsers > 0 && (
          <div className="mt-4 px-2">
            <PaginationFooter
              page={currentPage}
              pageSize={itemsPerPage}
              total={totalUsers}
              disabled={loadingUsers}
              pageSizeOptions={['5', '10', '20']}
              onPageChange={setCurrentPage}
              onPageSizeChange={(size) => { setItemsPerPage(size); setCurrentPage(1) }}
            />
          </div>
        )}
        </>
      )}
    </Card>

      {isAdmin && <AnnotationAuditCard />}

      {/* Edit User Modal */}
      {editingUser && (
        <EditUserModal
          user={editingUser}
          editForm={editForm}
          onEditFormChange={setEditForm}
          onSave={handleSaveUser}
          onClose={() => setEditingUser(null)}
        />
      )}

      {/* Create User Modal */}
      {showCreateUser && (
        <CreateUserModal
          createForm={createForm}
          onCreateFormChange={setCreateForm}
          onSubmit={handleCreateUser}
          onClose={() => {
            setShowCreateUser(false)
            setCreateForm({ username: '', password: '', nickname: '', role: 'pathologist', registration_email: '' })
            setUsersError(null)
          }}
          isCreating={creatingUser}
        />
      )}

    </>
  )
}
