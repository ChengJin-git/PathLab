import { Key, X, Clock, Trash2 } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Checkbox } from '../ui/checkbox'
import { UserListItem, DatasetPermission } from '../../api'

export interface PermissionModalProps {
  user: UserListItem
  permissions: DatasetPermission[]
  datasets: { dataset_id: string; dataset_name: string }[]
  selectedDatasetIds: string[]
  expiresInHours: string
  loadingPermissions: boolean
  grantingPermission: boolean
  onSelectedDatasetIdsChange: (ids: string[]) => void
  onExpiresInHoursChange: (hours: string) => void
  onGrantPermission: () => void
  onRevokePermission: (datasetId: string) => void
  onRevokeAllPermissions: () => void
  onClose: () => void
}

export function PermissionModal({
  user,
  permissions,
  datasets,
  selectedDatasetIds,
  expiresInHours,
  loadingPermissions,
  grantingPermission,
  onSelectedDatasetIdsChange,
  onExpiresInHoursChange,
  onGrantPermission,
  onRevokePermission,
  onRevokeAllPermissions,
  onClose
}: PermissionModalProps) {
  const availableDatasets = datasets.filter(d => !permissions.some(p => p.dataset_id === d.dataset_id && p.is_valid))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full p-6 max-h-[80vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center">
            <Key className="w-5 h-5 mr-2 text-purple-600" />
            Dataset Permissions - {user.nickname || user.email}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Current Permissions */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-medium text-gray-700">Current Permissions</h4>
            {!loadingPermissions && permissions.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onRevokeAllPermissions}
                className="h-auto py-1 px-2 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                title="Revoke all permissions"
              >
                <Trash2 className="w-3 h-3 mr-1" />
                Batch Revoke
              </Button>
            )}
          </div>
          {loadingPermissions ? (
            <div className="text-sm text-gray-500">Loading permissions...</div>
          ) : permissions.length === 0 ? (
            <div className="text-sm text-gray-500 italic py-4 text-center border border-dashed border-gray-200 rounded-lg">
              No dataset permissions granted
            </div>
          ) : (
            <div className="space-y-2">
              {permissions.map(perm => (
                <div
                  key={perm.id}
                  className={`flex items-center justify-between p-3 rounded-lg border ${perm.is_valid ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200 opacity-60'}`}
                >
                  <div className="flex-1">
                    <div className="font-medium text-gray-900">
                      {datasets.find(d => d.dataset_id === perm.dataset_id)?.dataset_name || perm.dataset_id}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {perm.expires_at ? `Expires: ${new Date(perm.expires_at).toLocaleString()}` : 'No expiration'}
                      </span>
                      {perm.is_expired && <span className="text-red-600 font-medium">Expired</span>}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onRevokePermission(perm.dataset_id)}
                    className="h-8 w-8 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                    title="Revoke permission"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Grant New Permission */}
        <div className="border-t border-gray-200 pt-6">
          <h4 className="text-sm font-medium text-gray-700 mb-3">Grant New Permission</h4>
          <div className="space-y-4">
            {/* Dataset Selection List */}
            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 max-h-[300px] overflow-y-auto">
              <div className="flex items-center space-x-2 pb-3 mb-2 border-b border-gray-200 sticky top-0 bg-gray-50 z-10">
                <Checkbox
                  id="select-all-datasets"
                  checked={availableDatasets.length > 0 && availableDatasets.every(d => selectedDatasetIds.includes(d.dataset_id))}
                  onCheckedChange={(checked) => {
                    if (checked === true) {
                      onSelectedDatasetIdsChange(availableDatasets.map(d => d.dataset_id))
                    } else {
                      onSelectedDatasetIdsChange([])
                    }
                  }}
                />
                <label htmlFor="select-all-datasets" className="text-sm font-medium text-gray-700 cursor-pointer">
                  Select All Available ({availableDatasets.length})
                </label>
              </div>
              <div className="space-y-2">
                {availableDatasets.map(d => (
                  <div key={d.dataset_id} className="flex items-center space-x-2 py-1 px-1 hover:bg-gray-100 rounded">
                    <Checkbox
                      id={`dataset-${d.dataset_id}`}
                      checked={selectedDatasetIds.includes(d.dataset_id)}
                      onCheckedChange={(checked) => {
                        onSelectedDatasetIdsChange(
                          checked === true
                            ? [...selectedDatasetIds, d.dataset_id]
                            : selectedDatasetIds.filter(id => id !== d.dataset_id)
                        )
                      }}
                    />
                    <label htmlFor={`dataset-${d.dataset_id}`} className="text-sm text-gray-700 cursor-pointer flex-1">
                      {d.dataset_name}
                    </label>
                  </div>
                ))}
                {availableDatasets.length === 0 && (
                  <div className="text-sm text-gray-500 italic text-center py-8">
                    No additional datasets available to grant.
                  </div>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-4 items-end bg-white p-4 rounded-lg border border-gray-100">
              <div className="w-40">
                <Label className="text-xs text-gray-500 mb-1.5 block">Expiration (Hours)</Label>
                <Input
                  type="number"
                  value={expiresInHours}
                  onChange={(e) => onExpiresInHoursChange(e.target.value)}
                  placeholder="Forever"
                  className="h-9"
                  min="1"
                  disabled={grantingPermission}
                />
              </div>
              <div className="flex-1">
                <p className="text-xs text-gray-400 mb-1">
                  Leave empty for permanent permission.
                </p>
              </div>
              <Button
                onClick={onGrantPermission}
                disabled={selectedDatasetIds.length === 0 || grantingPermission}
                className="bg-purple-600 hover:bg-purple-700 h-9"
              >
                {grantingPermission ? 'Granting...' : `Grant Access (${selectedDatasetIds.length})`}
              </Button>
            </div>
          </div>
        </div>

        {/* Close Button */}
        <div className="flex justify-end mt-6 pt-4 border-t border-gray-200">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  )
}
