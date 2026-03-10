import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, Clock, Database, Key, Search, Trash2, Users, X } from 'lucide-react'
import { Button } from '../ui/button'
import { Checkbox } from '../ui/checkbox'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import { cn } from '../../lib/utils'
import {
  batchGrantDatasetPermissions,
  batchRevokeDatasetPermissions,
  fetchDatasets,
  getUserDatasetPermissions,
  grantDatasetPermission,
  listDatasetPermissions,
  revokeDatasetPermission
} from '../../api'
import type { DatasetPermission } from '../../api/permissions'
import type { DatasetSummary } from '../../api/wsi'
import type { UserListItem } from '../../api/users'
import type { ShowConfirmDialog } from './ConfirmDialog'

type PermissionMode = 'user' | 'dataset'
type PermissionDataset = DatasetSummary & { dataset_id: string }

const PAGE_SIZE_OPTIONS = ['5', '10', '20']

export interface PermissionCenterModalProps {
  users: UserListItem[]
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
  onClose: () => void
  initialMode?: PermissionMode
  initialUserId?: string
}

function getRoleBadgeColor(role: string) {
  switch (role) {
    case 'admin': return 'bg-red-100 text-red-800 border-red-200'
    case 'pathologist': return 'bg-primary-100 text-primary-800 border-primary-200'
    case 'guest': return 'bg-gray-100 text-gray-800 border-gray-200'
    default: return 'bg-gray-100 text-gray-800 border-gray-200'
  }
}

function parsePositiveHours(value: string): number | undefined {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
}

function PaginationFooter({
  page,
  pageSize,
  total,
  disabled,
  onPageChange,
  onPageSizeChange,
  t
}: {
  page: number
  pageSize: number
  total: number
  disabled?: boolean
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
  t: (key: string, options?: Record<string, unknown>) => string
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1)

  return (
    <div className="flex flex-col gap-3 border-t border-gray-200 pt-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <span>{t('settings.permissionCenterModal.itemsPerPage')}</span>
        <Select
          value={String(pageSize)}
          onChange={(value) => onPageSizeChange(Number(value))}
          options={PAGE_SIZE_OPTIONS.map((value) => ({ value, label: value }))}
          className="w-20"
          disabled={disabled}
        />
      </div>

      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <span className="text-sm text-gray-500">
          {t('settings.permissionCenterModal.pageInfo', { current: Math.min(page, totalPages), total: totalPages, count: total })}
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={disabled || page <= 1}
            className="gap-1"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            {t('settings.permissionCenterModal.previous')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={disabled || page >= totalPages}
            className="gap-1"
          >
            {t('settings.permissionCenterModal.next')}
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}

export function PermissionCenterModal({
  users,
  showConfirmDialog,
  closeConfirmDialog,
  onClose,
  initialMode = 'dataset',
  initialUserId
}: PermissionCenterModalProps) {
  const { t } = useTranslation()
  const eligibleUsers = useMemo(() => users.filter((user) => user.role !== 'admin'), [users])

  const [mode, setMode] = useState<PermissionMode>(initialMode)
  const [selectedUserId, setSelectedUserId] = useState(initialUserId ?? '')
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [datasetSearchQuery, setDatasetSearchQuery] = useState('')
  const [datasetPage, setDatasetPage] = useState(1)
  const [datasetPageSize, setDatasetPageSize] = useState(10)
  const [datasetItems, setDatasetItems] = useState<DatasetSummary[]>([])
  const [datasetTotal, setDatasetTotal] = useState(0)
  const [userPermissions, setUserPermissions] = useState<DatasetPermission[]>([])
  const [datasetPermissions, setDatasetPermissions] = useState<DatasetPermission[]>([])
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([])
  const [selectedGrantUserIds, setSelectedGrantUserIds] = useState<string[]>([])
  const [grantUserSearchQuery, setGrantUserSearchQuery] = useState('')
  const [expiresInHours, setExpiresInHours] = useState('')
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [loadingUserPermissions, setLoadingUserPermissions] = useState(false)
  const [loadingDatasetPermissions, setLoadingDatasetPermissions] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedUser = useMemo(
    () => eligibleUsers.find((user) => user.id === selectedUserId) ?? null,
    [eligibleUsers, selectedUserId]
  )

  const pagedDatasets = useMemo(
    () => datasetItems.filter((item): item is PermissionDataset => Boolean(item.dataset_id)),
    [datasetItems]
  )

  const selectedDataset = useMemo(
    () => pagedDatasets.find((dataset) => dataset.dataset_id === selectedDatasetId) ?? null,
    [pagedDatasets, selectedDatasetId]
  )

  const validUserPermissions = useMemo(
    () => userPermissions.filter((permission) => permission.is_valid),
    [userPermissions]
  )

  const validUserDatasetIds = useMemo(
    () => new Set(validUserPermissions.map((permission) => permission.dataset_id)),
    [validUserPermissions]
  )

  const sortedUserPermissions = useMemo(() => {
    return [...userPermissions].sort((a, b) => {
      if (a.is_valid !== b.is_valid) return a.is_valid ? -1 : 1
      const aName = a.dataset_name || a.dataset_id
      const bName = b.dataset_name || b.dataset_id
      return aName.localeCompare(bName)
    })
  }, [userPermissions])

  const allVisibleDatasetsSelected = useMemo(() => {
    const selectableIds = pagedDatasets
      .filter((dataset) => !validUserDatasetIds.has(dataset.dataset_id))
      .map((dataset) => dataset.dataset_id)
    return selectableIds.length > 0 && selectableIds.every((datasetId) => selectedDatasetIds.includes(datasetId))
  }, [pagedDatasets, selectedDatasetIds, validUserDatasetIds])

  const userMap = useMemo(() => new Map(eligibleUsers.map((user) => [user.id, user])), [eligibleUsers])
  const validDatasetPermissionUserIds = useMemo(
    () => new Set(datasetPermissions.filter((permission) => permission.is_valid).map((permission) => permission.user_id)),
    [datasetPermissions]
  )

  const availableUsers = useMemo(() => {
    const query = grantUserSearchQuery.trim().toLowerCase()
    return eligibleUsers
      .filter((user) => !validDatasetPermissionUserIds.has(user.id))
      .filter((user) => {
        if (!query) return true
        return user.email.toLowerCase().includes(query) || (user.nickname || '').toLowerCase().includes(query)
      })
      .sort((a, b) => (a.nickname || a.email).localeCompare(b.nickname || b.email))
  }, [eligibleUsers, grantUserSearchQuery, validDatasetPermissionUserIds])

  const sortedDatasetPermissions = useMemo(() => {
    return [...datasetPermissions].sort((a, b) => {
      if (a.is_valid !== b.is_valid) return a.is_valid ? -1 : 1
      const aName = userMap.get(a.user_id)?.nickname || userMap.get(a.user_id)?.email || a.user_id
      const bName = userMap.get(b.user_id)?.nickname || userMap.get(b.user_id)?.email || b.user_id
      return aName.localeCompare(bName)
    })
  }, [datasetPermissions, userMap])

  const allVisibleUsersSelected = useMemo(
    () => availableUsers.length > 0 && availableUsers.every((user) => selectedGrantUserIds.includes(user.id)),
    [availableUsers, selectedGrantUserIds]
  )

  const loadDatasets = useCallback(async () => {
    setLoadingDatasets(true)
    try {
      const response = await fetchDatasets(undefined, {
        page: datasetPage,
        page_size: datasetPageSize,
        search: datasetSearchQuery.trim() || undefined
      })
      setDatasetItems(response.items)
      setDatasetTotal(response.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToLoadDatasets'))
    } finally {
      setLoadingDatasets(false)
    }
  }, [datasetPage, datasetPageSize, datasetSearchQuery, t])

  const loadUserPermissions = useCallback(async (userId: string) => {
    if (!userId) {
      setUserPermissions([])
      return
    }
    setLoadingUserPermissions(true)
    try {
      const response = await getUserDatasetPermissions(userId)
      setUserPermissions(response.permissions)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToLoadUserPermissions'))
    } finally {
      setLoadingUserPermissions(false)
    }
  }, [t])

  const loadDatasetPermissions = useCallback(async (datasetId: string) => {
    if (!datasetId) {
      setDatasetPermissions([])
      return
    }
    setLoadingDatasetPermissions(true)
    try {
      const response = await listDatasetPermissions(datasetId)
      setDatasetPermissions(response.permissions)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToLoadDatasetPermissions'))
    } finally {
      setLoadingDatasetPermissions(false)
    }
  }, [t])

  useEffect(() => {
    if (!selectedUserId) {
      const fallbackUserId = eligibleUsers.find((user) => user.id === initialUserId)?.id || eligibleUsers[0]?.id || ''
      if (fallbackUserId) {
        setSelectedUserId(fallbackUserId)
      }
      return
    }

    if (!eligibleUsers.some((user) => user.id === selectedUserId)) {
      setSelectedUserId(eligibleUsers[0]?.id || '')
    }
  }, [eligibleUsers, initialUserId, selectedUserId])

  useEffect(() => {
    void loadDatasets()
  }, [loadDatasets])

  useEffect(() => {
    if (mode === 'user') {
      void loadUserPermissions(selectedUserId)
    }
  }, [loadUserPermissions, mode, selectedUserId])

  useEffect(() => {
    if (mode !== 'dataset') return
    if (pagedDatasets.length === 0) {
      setSelectedDatasetId('')
      setDatasetPermissions([])
      return
    }

    if (!pagedDatasets.some((dataset) => dataset.dataset_id === selectedDatasetId)) {
      setSelectedDatasetId(pagedDatasets[0].dataset_id)
    }
  }, [mode, pagedDatasets, selectedDatasetId])

  useEffect(() => {
    if (mode === 'dataset' && selectedDatasetId) {
      void loadDatasetPermissions(selectedDatasetId)
    }
  }, [loadDatasetPermissions, mode, selectedDatasetId])

  const handleModeChange = (nextMode: PermissionMode) => {
    setMode(nextMode)
    setError(null)
    setSelectedDatasetIds([])
    setSelectedGrantUserIds([])
    setExpiresInHours('')
    setGrantUserSearchQuery('')
  }

  const handleDatasetSearchChange = (value: string) => {
    setDatasetSearchQuery(value)
    setDatasetPage(1)
  }

  const handleDatasetPageSizeChange = (pageSize: number) => {
    setDatasetPageSize(pageSize)
    setDatasetPage(1)
  }

  const handleToggleAllDatasets = (checked: boolean) => {
    const visibleIds = pagedDatasets
      .filter((dataset) => !validUserDatasetIds.has(dataset.dataset_id))
      .map((dataset) => dataset.dataset_id)

    if (checked) {
      setSelectedDatasetIds((prev) => Array.from(new Set([...prev, ...visibleIds])))
      return
    }

    const visibleIdSet = new Set(visibleIds)
    setSelectedDatasetIds((prev) => prev.filter((datasetId) => !visibleIdSet.has(datasetId)))
  }

  const handleToggleDataset = (datasetId: string, checked: boolean) => {
    setSelectedDatasetIds((prev) => checked ? Array.from(new Set([...prev, datasetId])) : prev.filter((id) => id !== datasetId))
  }

  const handleGrantToUser = async () => {
    if (!selectedUser || selectedDatasetIds.length === 0) return

    try {
      setSubmitting(true)
      setError(null)
      const hours = parsePositiveHours(expiresInHours)
      const results = await Promise.allSettled(
        selectedDatasetIds.map((datasetId) => grantDatasetPermission(datasetId, selectedUser.id, hours))
      )
      await loadUserPermissions(selectedUser.id)
      setSelectedDatasetIds([])
      setExpiresInHours('')

      const failedCount = results.filter((result) => result.status === 'rejected').length
      if (failedCount > 0) {
        setError(t('settings.permissionCenterModal.partialGrantWarning', { failed: failedCount }))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToGrantUserPermissions'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRevokeFromUser = (permission: DatasetPermission) => {
    if (!selectedUser) return

    showConfirmDialog({
      title: t('settings.permissionCenterModal.revokePermission'),
      message: t('settings.permissionCenterModal.revokeUserPermissionConfirm', {
        datasetName: permission.dataset_name || permission.dataset_id,
        userName: selectedUser.nickname || selectedUser.email
      }),
      confirmText: t('settings.usersTab.revoke'),
      confirmVariant: 'warning',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          setSubmitting(true)
          setError(null)
          await revokeDatasetPermission(permission.dataset_id, selectedUser.id)
          await loadUserPermissions(selectedUser.id)
        } catch (err) {
          setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToRevokeUserPermission'))
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  const handleRevokeAllFromUser = () => {
    if (!selectedUser || validUserPermissions.length === 0) return

    showConfirmDialog({
      title: t('settings.permissionCenterModal.revokeAllPermissions'),
      message: t('settings.permissionCenterModal.revokeAllUserPermissionsConfirm', {
        userName: selectedUser.nickname || selectedUser.email,
        count: validUserPermissions.length
      }),
      confirmText: t('settings.usersTab.revokeAll'),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          setSubmitting(true)
          setError(null)
          const results = await Promise.allSettled(
            validUserPermissions.map((permission) => revokeDatasetPermission(permission.dataset_id, selectedUser.id))
          )
          await loadUserPermissions(selectedUser.id)
          const failedCount = results.filter((result) => result.status === 'rejected').length
          if (failedCount > 0) {
            setError(t('settings.permissionCenterModal.partialRevokeWarning', { failed: failedCount }))
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToRevokeUserPermissions'))
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  const handleToggleAllUsers = (checked: boolean) => {
    if (checked) {
      setSelectedGrantUserIds((prev) => Array.from(new Set([...prev, ...availableUsers.map((user) => user.id)])))
      return
    }

    const visibleIds = new Set(availableUsers.map((user) => user.id))
    setSelectedGrantUserIds((prev) => prev.filter((userId) => !visibleIds.has(userId)))
  }

  const handleToggleGrantUser = (userId: string, checked: boolean) => {
    setSelectedGrantUserIds((prev) => checked ? Array.from(new Set([...prev, userId])) : prev.filter((id) => id !== userId))
  }

  const handleGrantToDataset = async () => {
    if (!selectedDatasetId || selectedGrantUserIds.length === 0) return

    try {
      setSubmitting(true)
      setError(null)
      const hours = parsePositiveHours(expiresInHours)
      const response = await batchGrantDatasetPermissions(selectedDatasetId, selectedGrantUserIds, hours)
      await loadDatasetPermissions(selectedDatasetId)
      setSelectedGrantUserIds([])
      setExpiresInHours('')
      if ((response.failed || 0) > 0) {
        setError(t('settings.permissionCenterModal.partialGrantWarning', { failed: response.failed }))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToGrantDatasetPermissions'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRevokeFromDataset = (permission: DatasetPermission) => {
    const userName = userMap.get(permission.user_id)?.nickname || userMap.get(permission.user_id)?.email || permission.user_id
    const datasetName = selectedDataset?.dataset_name || permission.dataset_id

    showConfirmDialog({
      title: t('settings.permissionCenterModal.revokePermission'),
      message: t('settings.permissionCenterModal.revokeDatasetPermissionConfirm', { userName, datasetName }),
      confirmText: t('settings.usersTab.revoke'),
      confirmVariant: 'warning',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          setSubmitting(true)
          setError(null)
          const response = await batchRevokeDatasetPermissions(permission.dataset_id, [permission.user_id])
          await loadDatasetPermissions(permission.dataset_id)
          if ((response.failed || 0) > 0) {
            setError(t('settings.permissionCenterModal.partialRevokeWarning', { failed: response.failed }))
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToRevokeDatasetPermission'))
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  const handleRevokeAllFromDataset = () => {
    const validPermissions = datasetPermissions.filter((permission) => permission.is_valid)
    if (!selectedDatasetId || validPermissions.length === 0) return

    showConfirmDialog({
      title: t('settings.permissionCenterModal.revokeAllPermissions'),
      message: t('settings.permissionCenterModal.revokeAllDatasetPermissionsConfirm', {
        datasetName: selectedDataset?.dataset_name || selectedDatasetId,
        count: validPermissions.length
      }),
      confirmText: t('settings.usersTab.revokeAll'),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          setSubmitting(true)
          setError(null)
          const response = await batchRevokeDatasetPermissions(selectedDatasetId, validPermissions.map((permission) => permission.user_id))
          await loadDatasetPermissions(selectedDatasetId)
          if ((response.failed || 0) > 0) {
            setError(t('settings.permissionCenterModal.partialRevokeWarning', { failed: response.failed }))
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : t('settings.permissionCenterModal.failedToRevokeDatasetPermissions'))
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-6xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
              <Key className="h-5 w-5 text-primary-600" />
              {t('settings.permissionCenterModal.title')}
            </h3>
            <p className="mt-1 text-sm text-gray-500">{t('settings.permissionCenterModal.description')}</p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 transition-colors hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mb-6 inline-flex rounded-2xl border border-gray-200 bg-gray-100 p-1">
          <button
            type="button"
            onClick={() => handleModeChange('user')}
            className={cn(
              'flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all',
              mode === 'user' ? 'bg-gray-900 text-white shadow-sm' : 'text-gray-600 hover:text-gray-900'
            )}
          >
            <Users className="h-4 w-4" />
            {t('settings.permissionCenterModal.byUser')}
          </button>
          <button
            type="button"
            onClick={() => handleModeChange('dataset')}
            className={cn(
              'flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all',
              mode === 'dataset' ? 'bg-gray-900 text-white shadow-sm' : 'text-gray-600 hover:text-gray-900'
            )}
          >
            <Database className="h-4 w-4" />
            {t('settings.permissionCenterModal.byDataset')}
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="mb-6 rounded-2xl border border-gray-200 bg-gray-50 p-4">
          <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex-1">
              <Label>{t('settings.permissionCenterModal.datasetBrowser')}</Label>
              <div className="relative mt-2">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                <Input
                  value={datasetSearchQuery}
                  onChange={(e) => handleDatasetSearchChange(e.target.value)}
                  placeholder={t('settings.permissionCenterModal.searchDatasets')}
                  className="pl-9"
                  disabled={loadingDatasets || submitting}
                />
              </div>
            </div>
            <div className="text-sm text-gray-500">
              {t('settings.permissionCenterModal.datasetCount', { count: datasetTotal })}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {loadingDatasets ? (
              <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
                {t('settings.permissionCenterModal.loadingDatasets')}
              </div>
            ) : pagedDatasets.length === 0 ? (
              <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
                {t('settings.permissionCenterModal.noDatasets')}
              </div>
            ) : (
              pagedDatasets.map((dataset) => {
                const alreadyGranted = validUserDatasetIds.has(dataset.dataset_id)
                const selectedInUserMode = selectedDatasetIds.includes(dataset.dataset_id)
                const selectedInDatasetMode = selectedDatasetId === dataset.dataset_id

                return (
                  <div
                    key={dataset.dataset_id}
                    className={cn(
                      'rounded-xl border p-4 transition-all',
                      mode === 'dataset' && selectedInDatasetMode
                        ? 'border-gray-900 bg-gray-900 text-white shadow-md'
                        : 'border-gray-200 bg-white hover:border-gray-300'
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <button
                          type="button"
                          onClick={() => setSelectedDatasetId(dataset.dataset_id)}
                          className={cn(
                            'block w-full text-left',
                            mode !== 'dataset' && 'cursor-default'
                          )}
                        >
                          <div className="truncate text-sm font-semibold">{dataset.dataset_name}</div>
                          <div className={cn('mt-1 text-xs', mode === 'dataset' && selectedInDatasetMode ? 'text-gray-300' : 'text-gray-500')}>
                            {t('settings.permissionCenterModal.datasetMeta', { count: dataset.file_count })}
                          </div>
                        </button>
                      </div>

                      {mode === 'user' && (
                        <Checkbox
                          checked={selectedInUserMode}
                          disabled={alreadyGranted || submitting}
                          onCheckedChange={(checked) => handleToggleDataset(dataset.dataset_id, checked)}
                        />
                      )}
                    </div>

                    {mode === 'user' && alreadyGranted && (
                      <div className="mt-3 inline-flex rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
                        {t('settings.permissionCenterModal.alreadyGranted')}
                      </div>
                    )}
                  </div>
                )
              })
            )}
          </div>

          <div className="mt-4">
            <PaginationFooter
              page={datasetPage}
              pageSize={datasetPageSize}
              total={datasetTotal}
              disabled={loadingDatasets || submitting}
              onPageChange={setDatasetPage}
              onPageSizeChange={handleDatasetPageSizeChange}
              t={t}
            />
          </div>
        </div>

        {mode === 'user' ? (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <div className="mb-4 space-y-2">
                <Label>{t('settings.permissionCenterModal.selectUser')}</Label>
                <Select
                  value={selectedUserId}
                  onChange={(value) => {
                    setSelectedUserId(value)
                    setSelectedDatasetIds([])
                    setExpiresInHours('')
                    setError(null)
                  }}
                  options={eligibleUsers.map((user) => ({
                    value: user.id,
                    label: `${user.nickname || user.email} (${user.email})`
                  }))}
                  placeholder={t('settings.permissionCenterModal.selectUserPlaceholder')}
                />
              </div>

              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-medium text-gray-900">{t('settings.permissionCenterModal.currentPermissions')}</h4>
                  <p className="mt-1 text-xs text-gray-500">
                    {t('settings.permissionCenterModal.currentPermissionsCount', { count: validUserPermissions.length })}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleRevokeAllFromUser}
                  disabled={validUserPermissions.length === 0 || submitting || loadingUserPermissions}
                  className="text-red-600 hover:bg-red-50 hover:text-red-700"
                >
                  <Trash2 className="mr-1 h-3.5 w-3.5" />
                  {t('settings.permissionCenterModal.revokeAll')}
                </Button>
              </div>

              {loadingUserPermissions ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                  {t('settings.permissionCenterModal.loadingUserPermissions')}
                </div>
              ) : sortedUserPermissions.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                  {t('settings.permissionCenterModal.noCurrentPermissions')}
                </div>
              ) : (
                <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
                  {sortedUserPermissions.map((permission) => (
                    <div
                      key={permission.id}
                      className={cn(
                        'flex items-start justify-between gap-3 rounded-xl border p-3',
                        permission.is_valid ? 'border-green-200 bg-green-50/40' : 'border-gray-200 bg-gray-50 opacity-70'
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-gray-900">
                          {permission.dataset_name || permission.dataset_id}
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                          <span className="inline-flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {permission.expires_at
                              ? t('settings.permissionModal.expires', { date: new Date(permission.expires_at).toLocaleString() })
                              : t('settings.permissionModal.noExpiration')}
                          </span>
                          {!permission.is_valid && (
                            <span className="font-medium text-red-600">{t('settings.permissionModal.expired')}</span>
                          )}
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRevokeFromUser(permission)}
                        disabled={submitting}
                        className="h-8 w-8 p-0 text-red-600 hover:bg-red-50 hover:text-red-700"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-medium text-gray-900">{t('settings.permissionCenterModal.grantDatasets')}</h4>
                  <p className="mt-1 text-xs text-gray-500">
                    {t('settings.permissionCenterModal.visibleDatasetsCount', { count: pagedDatasets.length })}
                  </p>
                </div>
              </div>

              <div className="mb-4 flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3">
                <Checkbox checked={allVisibleDatasetsSelected} onCheckedChange={handleToggleAllDatasets} />
                <span className="text-sm text-gray-700">
                  {t('settings.permissionCenterModal.selectVisibleDatasets', { count: pagedDatasets.length })}
                </span>
              </div>

              <div className="rounded-xl border border-gray-100 bg-gray-50 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                  <div className="sm:w-48">
                    <Label className="mb-1.5 block text-xs text-gray-500">{t('settings.permissionModal.expirationHours')}</Label>
                    <Input
                      type="number"
                      min="1"
                      value={expiresInHours}
                      onChange={(e) => setExpiresInHours(e.target.value)}
                      placeholder={t('settings.permissionModal.forever')}
                      disabled={submitting}
                    />
                  </div>
                  <div className="flex-1 text-xs text-gray-400">{t('settings.permissionModal.leaveEmptyForPermanent')}</div>
                  <Button
                    type="button"
                    onClick={handleGrantToUser}
                    disabled={selectedDatasetIds.length === 0 || !selectedUser || submitting}
                    className="bg-purple-600 hover:bg-purple-700"
                  >
                    {submitting
                      ? t('settings.permissionCenterModal.granting')
                      : t('settings.permissionCenterModal.grantSelectedDatasets', { count: selectedDatasetIds.length })}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-medium text-gray-900">{t('settings.permissionCenterModal.currentAccess')}</h4>
                  <p className="mt-1 text-xs text-gray-500">
                    {t('settings.permissionCenterModal.currentAccessCount', { count: datasetPermissions.filter((permission) => permission.is_valid).length })}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleRevokeAllFromDataset}
                  disabled={datasetPermissions.filter((permission) => permission.is_valid).length === 0 || submitting || loadingDatasetPermissions}
                  className="text-red-600 hover:bg-red-50 hover:text-red-700"
                >
                  <Trash2 className="mr-1 h-3.5 w-3.5" />
                  {t('settings.permissionCenterModal.revokeAll')}
                </Button>
              </div>

              {loadingDatasetPermissions ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                  {t('settings.permissionCenterModal.loadingDatasetPermissions')}
                </div>
              ) : sortedDatasetPermissions.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                  {t('settings.permissionCenterModal.noCurrentAccess')}
                </div>
              ) : (
                <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
                  {sortedDatasetPermissions.map((permission) => {
                    const permissionUser = userMap.get(permission.user_id)
                    const displayName = permissionUser?.nickname || permissionUser?.email || permission.user_id
                    return (
                      <div
                        key={permission.id}
                        className={cn(
                          'flex items-start justify-between gap-3 rounded-xl border p-3',
                          permission.is_valid ? 'border-green-200 bg-green-50/40' : 'border-gray-200 bg-gray-50 opacity-70'
                        )}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-gray-900">{displayName}</div>
                          {permissionUser?.email && <div className="mt-1 truncate text-xs text-gray-500">{permissionUser.email}</div>}
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            {permissionUser && (
                              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${getRoleBadgeColor(permissionUser.role)}`}>
                                {t(`settings.usersTab.role_${permissionUser.role}`)}
                              </span>
                            )}
                            <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                              <Clock className="h-3 w-3" />
                              {permission.expires_at
                                ? t('settings.permissionModal.expires', { date: new Date(permission.expires_at).toLocaleString() })
                                : t('settings.permissionModal.noExpiration')}
                            </span>
                            {!permission.is_valid && (
                              <span className="text-xs font-medium text-red-600">{t('settings.permissionModal.expired')}</span>
                            )}
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRevokeFromDataset(permission)}
                          disabled={submitting}
                          className="h-8 w-8 p-0 text-red-600 hover:bg-red-50 hover:text-red-700"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-gray-200 bg-white p-4">
              <div className="mb-3">
                <h4 className="text-sm font-medium text-gray-900">{t('settings.permissionCenterModal.grantUsers')}</h4>
                <p className="mt-1 text-xs text-gray-500">
                  {selectedDataset
                    ? t('settings.permissionCenterModal.selectedDatasetName', { name: selectedDataset.dataset_name })
                    : t('settings.permissionCenterModal.selectDatasetHint')}
                </p>
              </div>

              <div className="relative mb-3">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                <Input
                  value={grantUserSearchQuery}
                  onChange={(e) => setGrantUserSearchQuery(e.target.value)}
                  placeholder={t('settings.permissionCenterModal.searchUsers')}
                  className="pl-9"
                  disabled={submitting}
                />
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                <div className="mb-3 flex items-center gap-2 border-b border-gray-200 pb-3">
                  <Checkbox checked={allVisibleUsersSelected} onCheckedChange={handleToggleAllUsers} />
                  <span className="text-sm text-gray-700">
                    {t('settings.permissionCenterModal.selectVisibleUsers', { count: availableUsers.length })}
                  </span>
                </div>

                <div className="max-h-[260px] space-y-2 overflow-y-auto pr-1">
                  {availableUsers.map((user) => (
                    <div key={user.id} className="flex items-start gap-2 rounded-xl bg-white p-3">
                      <Checkbox
                        checked={selectedGrantUserIds.includes(user.id)}
                        onCheckedChange={(checked) => handleToggleGrantUser(user.id, checked)}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-gray-900">{user.nickname || user.email}</div>
                        <div className="mt-1 truncate text-xs text-gray-500">{user.email}</div>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${getRoleBadgeColor(user.role)}`}>
                            {t(`settings.usersTab.role_${user.role}`)}
                          </span>
                          <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs ${user.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-600'}`}>
                            {user.is_active ? t('settings.usersTab.active') : t('settings.usersTab.inactive')}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}

                  {availableUsers.length === 0 && (
                    <div className="py-8 text-center text-sm text-gray-500">
                      {eligibleUsers.some((user) => !validDatasetPermissionUserIds.has(user.id))
                        ? t('settings.permissionCenterModal.noUsersMatchingSearch')
                        : t('settings.permissionCenterModal.noUsersAvailable')}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                  <div className="sm:w-48">
                    <Label className="mb-1.5 block text-xs text-gray-500">{t('settings.permissionModal.expirationHours')}</Label>
                    <Input
                      type="number"
                      min="1"
                      value={expiresInHours}
                      onChange={(e) => setExpiresInHours(e.target.value)}
                      placeholder={t('settings.permissionModal.forever')}
                      disabled={submitting}
                    />
                  </div>
                  <div className="flex-1 text-xs text-gray-400">{t('settings.permissionModal.leaveEmptyForPermanent')}</div>
                  <Button
                    type="button"
                    onClick={handleGrantToDataset}
                    disabled={!selectedDatasetId || selectedGrantUserIds.length === 0 || submitting}
                    className="bg-purple-600 hover:bg-purple-700"
                  >
                    {submitting
                      ? t('settings.permissionCenterModal.granting')
                      : t('settings.permissionCenterModal.grantSelectedUsers', { count: selectedGrantUserIds.length })}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="mt-6 flex justify-end border-t border-gray-200 pt-4">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('settings.permissionModal.close')}
          </Button>
        </div>
      </div>
    </div>
  )
}