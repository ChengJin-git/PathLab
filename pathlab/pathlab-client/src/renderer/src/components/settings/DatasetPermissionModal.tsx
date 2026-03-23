import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Database, Search, Clock, Trash2, X, Globe, Lock } from 'lucide-react'
import { Button } from '../ui/button'
import { Tooltip } from '../ui/tooltip'
import { Checkbox } from '../ui/checkbox'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import {
  fetchDatasets,
  grantDatasetGrant,
  listDatasetGrants,
  listUsers,
  revokeDatasetGrant,
  updateDatasetVisibility
} from '../../api'
import type { DatasetGrant, UserListItem } from '../../api'
import type { ShowConfirmDialog } from './ConfirmDialog'

export interface DatasetGrantModalProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
  onClose: () => void
}

type PermissionDataset = { dataset_id: string; dataset_name: string; is_public: boolean }

function getRoleBadgeColor(role: string) {
  switch (role) {
    case 'admin': return 'bg-red-100 text-red-800 border-red-200'
    case 'pathologist': return 'bg-primary-100 text-primary-800 border-primary-200'
    case 'guest': return 'bg-gray-100 text-gray-800 border-gray-200'
    default: return 'bg-gray-100 text-gray-800 border-gray-200'
  }
}

export function DatasetGrantModal({ showConfirmDialog, closeConfirmDialog, onClose }: DatasetGrantModalProps) {
  const { t } = useTranslation()
  const [users, setUsers] = useState<UserListItem[]>([])
  const [datasets, setDatasets] = useState<PermissionDataset[]>([])
  const [permissions, setPermissions] = useState<DatasetGrant[]>([])
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [selectedDatasetIsPublic, setSelectedDatasetIsPublic] = useState(false)
  const [togglingVisibility, setTogglingVisibility] = useState(false)
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([])
  const [userSearchQuery, setUserSearchQuery] = useState('')
  const [expiresInHours, setExpiresInHours] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loadingData, setLoadingData] = useState(false)
  const [loadingPermissions, setLoadingPermissions] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const loadDatasetGrantList = useCallback(async (datasetId: string) => {
    if (!datasetId) {
      setPermissions([])
      return
    }
    setLoadingPermissions(true)
    setError(null)
    try {
      const response = await listDatasetGrants(datasetId)
      setPermissions(response.grants)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.datasetPermissionModal.failedToLoadPermissions'))
    } finally {
      setLoadingPermissions(false)
    }
  }, [t])

  const loadInitialData = useCallback(async () => {
    setLoadingData(true)
    setError(null)
    try {
      const [userList, datasetResponse] = await Promise.all([listUsers(), fetchDatasets()])
      const permissionDatasets = datasetResponse.items
        .filter((dataset) => dataset.dataset_id !== null)
        .map((dataset) => ({
          dataset_id: dataset.dataset_id!,
          dataset_name: dataset.dataset_name,
          is_public: dataset.is_public ?? false,
        }))
        .sort((a, b) => a.dataset_name.localeCompare(b.dataset_name))

      setUsers(userList)
      setDatasets(permissionDatasets)

      const initialDatasetId = permissionDatasets[0]?.dataset_id ?? ''
      setSelectedDatasetId(initialDatasetId)
      setSelectedDatasetIsPublic(permissionDatasets[0]?.is_public ?? false)
      setSelectedUserIds([])
      setUserSearchQuery('')
      setExpiresInHours('')

      if (initialDatasetId) {
        await loadDatasetGrantList(initialDatasetId)
      } else {
        setPermissions([])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.datasetPermissionModal.failedToLoad'))
    } finally {
      setLoadingData(false)
    }
  }, [loadDatasetGrantList, t])

  useEffect(() => {
    void loadInitialData()
  }, [loadInitialData])

  const datasetMap = useMemo(() => new Map(datasets.map((dataset) => [dataset.dataset_id, dataset])), [datasets])
  const userMap = useMemo(() => new Map(users.map((user) => [user.id, user])), [users])
  const eligibleUsers = useMemo(() => users.filter((user) => user.role !== 'admin'), [users])
  const validPermissionUserIds = useMemo(() => new Set(permissions.filter((permission) => permission.is_valid).map((permission) => permission.user_id)), [permissions])
  const availableUsers = useMemo(() => {
    const query = userSearchQuery.trim().toLowerCase()
    return eligibleUsers
      .filter((user) => !validPermissionUserIds.has(user.id))
      .filter((user) => !query || user.email.toLowerCase().includes(query) || (user.nickname || '').toLowerCase().includes(query))
      .sort((a, b) => (a.nickname || a.email).localeCompare(b.nickname || b.email))
  }, [eligibleUsers, userSearchQuery, validPermissionUserIds])
  const sortedPermissions = useMemo(() => {
    return [...permissions].sort((a, b) => {
      if (a.is_valid !== b.is_valid) return a.is_valid ? -1 : 1
      const aName = userMap.get(a.user_id)?.nickname || userMap.get(a.user_id)?.email || a.user_id
      const bName = userMap.get(b.user_id)?.nickname || userMap.get(b.user_id)?.email || b.user_id
      return aName.localeCompare(bName)
    })
  }, [permissions, userMap])
  const validPermissionCount = useMemo(() => permissions.filter((permission) => permission.is_valid).length, [permissions])
  const allAvailableSelected = availableUsers.length > 0 && availableUsers.every((user) => selectedUserIds.includes(user.id))

  const handleDatasetChange = (datasetId: string) => {
    const ds = datasets.find(d => d.dataset_id === datasetId)
    setSelectedDatasetId(datasetId)
    setSelectedDatasetIsPublic(ds?.is_public ?? false)
    setSelectedUserIds([])
    setUserSearchQuery('')
    setExpiresInHours('')
    void loadDatasetGrantList(datasetId)
  }

  const handleToggleVisibility = async () => {
    if (!selectedDatasetId) return
    setTogglingVisibility(true)
    setError(null)
    try {
      const newValue = !selectedDatasetIsPublic
      const result = await updateDatasetVisibility(selectedDatasetId, newValue)
      setSelectedDatasetIsPublic(result.is_public)
      setDatasets(prev => prev.map(d => d.dataset_id === selectedDatasetId
        ? { ...d, is_public: result.is_public }
        : d
      ))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.datasetPermissionModal.failedToUpdateVisibility'))
    } finally {
      setTogglingVisibility(false)
    }
  }


  const handleToggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedUserIds((prev) => Array.from(new Set([...prev, ...availableUsers.map((user) => user.id)])))
      return
    }
    const filteredIds = new Set(availableUsers.map((user) => user.id))
    setSelectedUserIds((prev) => prev.filter((userId) => !filteredIds.has(userId)))
  }

  const handleToggleUser = (userId: string, checked: boolean) => {
    setSelectedUserIds((prev) => checked ? [...prev, userId] : prev.filter((id) => id !== userId))
  }

  const handleGrantPermissions = async () => {
    if (!selectedDatasetId || selectedUserIds.length === 0) return
    const parsedHours = expiresInHours.trim() ? Number.parseInt(expiresInHours, 10) : undefined
    const hours = parsedHours && parsedHours > 0 ? parsedHours : undefined

    try {
      setSubmitting(true)
      setError(null)
      const results = await Promise.allSettled(selectedUserIds.map((userId) => grantDatasetGrant(selectedDatasetId, userId, hours)))
      await loadDatasetGrantList(selectedDatasetId)
      setSelectedUserIds([])
      setExpiresInHours('')
      if (results.some((result) => result.status === 'rejected')) {
        setError(t('settings.datasetPermissionModal.failedToGrantPermissions'))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.datasetPermissionModal.failedToGrantPermissions'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRevokePermission = (permission: DatasetGrant) => {
    const datasetName = datasetMap.get(permission.dataset_id)?.dataset_name || permission.dataset_id
    const userName = userMap.get(permission.user_id)?.nickname || userMap.get(permission.user_id)?.email || permission.user_id

    showConfirmDialog({
      title: t('settings.datasetPermissionModal.revokePermission'),
      message: t('settings.datasetPermissionModal.revokePermissionConfirm', { datasetName, userName }),
      confirmText: t('settings.usersTab.revoke'),
      confirmVariant: 'warning',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          setSubmitting(true)
          setError(null)
          await revokeDatasetGrant(permission.dataset_id, permission.user_id)
          await loadDatasetGrantList(permission.dataset_id)
        } catch (err) {
          setError(err instanceof Error ? err.message : t('settings.datasetPermissionModal.failedToRevokePermission'))
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  const handleRevokeAllPermissions = () => {
    if (!selectedDatasetId || validPermissionCount === 0) return
    const datasetName = datasetMap.get(selectedDatasetId)?.dataset_name || selectedDatasetId
    const validPermissions = permissions.filter((permission) => permission.is_valid)

    showConfirmDialog({
      title: t('settings.datasetPermissionModal.revokeAllPermissions'),
      message: t('settings.datasetPermissionModal.revokeAllPermissionsConfirm', { datasetName, count: validPermissions.length }),
      confirmText: t('settings.usersTab.revokeAll'),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          setSubmitting(true)
          setError(null)
          const results = await Promise.allSettled(validPermissions.map((permission) => revokeDatasetGrant(selectedDatasetId, permission.user_id)))
          await loadDatasetGrantList(selectedDatasetId)
          if (results.some((result) => result.status === 'rejected')) {
            setError(t('settings.datasetPermissionModal.failedToRevokePermissions'))
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : t('settings.datasetPermissionModal.failedToRevokePermissions'))
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-5xl w-full p-6 max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 flex items-center">
              <Database className="w-5 h-5 mr-2 text-primary-600" />
              {t('settings.datasetPermissionModal.title')}
            </h3>
            <p className="text-sm text-gray-500 mt-1">{t('settings.datasetPermissionModal.description')}</p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mb-4 p-4 bg-red-100 border border-red-300 rounded-lg text-red-600 text-sm">
            {error}
          </div>
        )}

        {loadingData ? (
          <div className="py-12 text-center text-sm text-gray-500">{t('settings.datasetPermissionModal.loadingData')}</div>
        ) : datasets.length === 0 ? (
          <div className="py-12 text-center text-sm text-gray-500 border border-dashed border-gray-200 rounded-lg">
            {t('settings.datasetPermissionModal.noDatasets')}
          </div>
        ) : (
          <>
            <div className="mb-6 space-y-2">
              <Label>{t('settings.datasetPermissionModal.dataset')}</Label>
              <Select
                value={selectedDatasetId}
                onChange={handleDatasetChange}
                options={datasets.map((dataset) => ({ value: dataset.dataset_id, label: dataset.dataset_name }))}
                placeholder={t('settings.datasetPermissionModal.selectDataset')}
              />
              {selectedDatasetId && (
                <div className="space-y-2 pt-1">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                      {selectedDatasetIsPublic ? (
                        <Globe className="w-4 h-4 text-blue-500" />
                      ) : (
                        <Lock className="w-4 h-4 text-gray-400" />
                      )}
                      <span>
                        {selectedDatasetIsPublic
                          ? t('settings.datasetPermissionModal.visibilityPublic')
                          : t('settings.datasetPermissionModal.visibilityPrivate')}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={handleToggleVisibility}
                      disabled={togglingVisibility}
                      className={`text-xs px-3 py-1.5 rounded-lg font-medium border transition-colors ${
                        selectedDatasetIsPublic
                          ? 'border-gray-200 text-gray-600 hover:bg-gray-50'
                          : 'border-blue-200 text-blue-600 hover:bg-blue-50'
                      }`}
                    >
                      {togglingVisibility
                        ? t('settings.datasetPermissionModal.updating')
                        : selectedDatasetIsPublic
                          ? t('settings.datasetPermissionModal.makePrivate')
                          : t('settings.datasetPermissionModal.makePublic')}
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <div className="border border-gray-200 rounded-xl p-4 bg-gray-50/60">
                <div className="flex items-center justify-between gap-3 mb-3">
                  <div>
                    <h4 className="text-sm font-medium text-gray-800">{t('settings.datasetPermissionModal.currentAccess')}</h4>
                    <p className="text-xs text-gray-500 mt-1">
                      {t('settings.datasetPermissionModal.currentAccessCount', { count: validPermissionCount })}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRevokeAllPermissions}
                    disabled={validPermissionCount === 0 || submitting || loadingPermissions}
                    className="h-auto py-1 px-2 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                  >
                    <Trash2 className="w-3 h-3 mr-1" />
                    {t('settings.datasetPermissionModal.revokeAll')}
                  </Button>
                </div>

                {loadingPermissions ? (
                  <div className="text-sm text-gray-500 py-10 text-center">{t('settings.datasetPermissionModal.loadingPermissions')}</div>
                ) : sortedPermissions.length === 0 ? (
                  <div className="text-sm text-gray-500 italic py-10 text-center border border-dashed border-gray-200 rounded-lg bg-white">
                    {t('settings.datasetPermissionModal.noCurrentAccess')}
                  </div>
                ) : (
                  <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                    {sortedPermissions.map((permission) => {
                      const user = userMap.get(permission.user_id)
                      const displayName = user?.nickname || user?.email || permission.user_id
                      return (
                        <div
                          key={permission.id}
                          className={`flex items-start justify-between gap-3 p-3 rounded-lg border ${permission.is_valid ? 'bg-white border-green-200' : 'bg-gray-100 border-gray-200 opacity-70'}`}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="font-medium text-gray-900 truncate">{displayName}</div>
                            {user?.email && <div className="text-xs text-gray-500 mt-1 truncate">{user.email}</div>}
                            <div className="flex flex-wrap items-center gap-2 mt-2">
                              {user && (
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${getRoleBadgeColor(user.role)}`}>
                                  {t(`settings.usersTab.role_${user.role}`)}
                                </span>
                              )}
                              {user && (
                                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-200 text-gray-600'}`}>
                                  {user.is_active ? t('settings.usersTab.active') : t('settings.usersTab.inactive')}
                                </span>
                              )}
                              <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                                <Clock className="w-3 h-3" />
                                {permission.expires_at ? t('settings.permissionModal.expires', { date: new Date(permission.expires_at).toLocaleString() }) : t('settings.permissionModal.noExpiration')}
                              </span>
                              {!permission.is_valid && (
                                <span className="text-xs font-medium text-red-600">{t('settings.permissionModal.expired')}</span>
                              )}
                            </div>
                          </div>
                          <Tooltip content={t('settings.datasetPermissionModal.revokePermission')}>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleRevokePermission(permission)}
                              disabled={submitting}
                              className="h-8 w-8 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </Tooltip>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              <div className="border border-gray-200 rounded-xl p-4 bg-white">
                <div className="mb-3">
                  <h4 className="text-sm font-medium text-gray-800">{t('settings.datasetPermissionModal.grantAccess')}</h4>
                  <p className="text-xs text-gray-500 mt-1">
                    {t('settings.datasetPermissionModal.availableUsersCount', { count: availableUsers.length })}
                  </p>
                </div>

                <div className="relative mb-3">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" />
                  <Input
                    value={userSearchQuery}
                    onChange={(e) => setUserSearchQuery(e.target.value)}
                    placeholder={t('settings.datasetPermissionModal.searchUsers')}
                    className="pl-9 h-9"
                  />
                </div>

                <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 max-h-[340px] overflow-y-auto">
                  <div className="flex items-center space-x-2 pb-3 mb-2 border-b border-gray-200 sticky top-0 bg-gray-50 z-10">
                    <Checkbox
                      id="select-all-dataset-users"
                      checked={allAvailableSelected}
                      onCheckedChange={(checked) => handleToggleSelectAll(checked === true)}
                    />
                    <label htmlFor="select-all-dataset-users" className="text-sm font-medium text-gray-700 cursor-pointer">
                      {t('settings.datasetPermissionModal.selectAllFiltered', { count: availableUsers.length })}
                    </label>
                  </div>

                  <div className="space-y-2">
                    {availableUsers.map((user) => (
                      <div key={user.id} className="flex items-start space-x-2 py-2 px-2 hover:bg-gray-100 rounded">
                        <Checkbox
                          id={`permission-user-${user.id}`}
                          checked={selectedUserIds.includes(user.id)}
                          onCheckedChange={(checked) => handleToggleUser(user.id, checked === true)}
                        />
                        <label htmlFor={`permission-user-${user.id}`} className="text-sm text-gray-700 cursor-pointer flex-1 min-w-0">
                          <div className="font-medium truncate">{user.nickname || user.email}</div>
                          <div className="text-xs text-gray-500 truncate mt-0.5">{user.email}</div>
                          <div className="flex flex-wrap items-center gap-2 mt-2">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${getRoleBadgeColor(user.role)}`}>
                              {t(`settings.usersTab.role_${user.role}`)}
                            </span>
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-200 text-gray-600'}`}>
                              {user.is_active ? t('settings.usersTab.active') : t('settings.usersTab.inactive')}
                            </span>
                          </div>
                        </label>
                      </div>
                    ))}

                    {availableUsers.length === 0 && (
                      <div className="text-sm text-gray-500 italic text-center py-8">
                        {eligibleUsers.some((user) => !validPermissionUserIds.has(user.id))
                          ? t('settings.datasetPermissionModal.noUsersMatchingSearch')
                          : t('settings.datasetPermissionModal.noUsersAvailable')}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex flex-col sm:flex-row gap-3 sm:gap-4 sm:items-end bg-gray-50 p-4 rounded-lg border border-gray-100 mt-4">
                  <div className="w-full sm:w-40">
                    <Label className="text-xs text-gray-500 mb-1.5 block">{t('settings.permissionModal.expirationHours')}</Label>
                    <Input
                      type="number"
                      value={expiresInHours}
                      onChange={(e) => setExpiresInHours(e.target.value)}
                      placeholder={t('settings.permissionModal.forever')}
                      className="h-9"
                      min="1"
                      disabled={submitting}
                    />
                    <p className="text-xs text-gray-400 mt-1 sm:hidden">{t('settings.permissionModal.leaveEmptyForPermanent')}</p>
                  </div>
                  <div className="flex-1 hidden sm:block">
                    <p className="text-xs text-gray-400 mb-1">{t('settings.permissionModal.leaveEmptyForPermanent')}</p>
                  </div>
                  <Button
                    onClick={handleGrantPermissions}
                    disabled={selectedUserIds.length === 0 || submitting || loadingPermissions}
                    className="bg-purple-600 hover:bg-purple-700 h-9 w-full sm:w-auto"
                  >
                    {submitting ? t('settings.datasetPermissionModal.granting') : t('settings.datasetPermissionModal.grantSelected', { count: selectedUserIds.length })}
                  </Button>
                </div>
              </div>
            </div>
          </>
        )}

        <div className="flex justify-end mt-6 pt-4 border-t border-gray-200">
          <Button variant="outline" onClick={onClose}>{t('settings.permissionModal.close')}</Button>
        </div>
      </div>
    </div>
  )
}
