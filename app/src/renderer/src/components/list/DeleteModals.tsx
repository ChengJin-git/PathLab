import { useTranslation } from 'react-i18next'
import type { WSIStorageInfo } from '../../api/storage'
import { ModalShell } from '../ui/modal-shell'
import { Button } from '../ui/button'

export interface DeleteConfirmModalProps {
  wsiToDelete: { wsi_id: string; label: string; original_filename?: string }
  wsiStorageInfo: WSIStorageInfo | null
  loadingStorageInfo: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteConfirmModal({ wsiToDelete, onCancel, onConfirm }: DeleteConfirmModalProps) {
  const { t } = useTranslation()
  return <ModalShell isOpen maxWidth="md" className="p-5 sm:p-6">
    <h3 className="text-lg font-semibold text-gray-900">{t('listComponents.deleteSlide')}</h3>
    <p className="mt-3 break-all text-sm text-gray-700">{wsiToDelete.original_filename || wsiToDelete.wsi_id}</p>
    <p className="mt-3 text-sm text-gray-500">{t('settings.storageInventory.imageDeleteDescription')}</p>
    <div className="mt-6 flex justify-end gap-2">
      <Button variant="outline" onClick={onCancel}>{t('common.cancel')}</Button>
      <Button className="bg-red-600 text-white hover:bg-red-700" onClick={onConfirm}>{t('common.delete')}</Button>
    </div>
  </ModalShell>
}

export interface BatchDeleteModalProps {
  selectedIds: Set<string>
  selectedCount?: number
  datasetToDeleteId: string | null
  datasetToDeleteName: string
  deleting: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function BatchDeleteModal({ selectedIds, selectedCount, datasetToDeleteId, datasetToDeleteName, deleting, onCancel, onConfirm }: BatchDeleteModalProps) {
  const { t } = useTranslation()
  const count = selectedCount ?? selectedIds.size
  return <ModalShell isOpen maxWidth="md" className="p-5 sm:p-6">
    <h3 className="text-lg font-semibold text-gray-900">{t(datasetToDeleteId ? 'listComponents.deleteDataset' : 'listComponents.deleteMultipleSlides')}</h3>
    <p className="mt-3 text-sm text-gray-700">{datasetToDeleteId && `${datasetToDeleteName} · `}{t('listComponents.fileCount', { count })}</p>
    <p className="mt-3 text-sm text-gray-500">{t('settings.storageInventory.imageDeleteDescription')}</p>
    <div className="mt-6 flex justify-end gap-2">
      <Button variant="outline" disabled={deleting} onClick={onCancel}>{t('common.cancel')}</Button>
      <Button className="bg-red-600 text-white hover:bg-red-700" disabled={deleting} onClick={onConfirm}>{t(deleting ? 'listComponents.deleting' : 'common.delete')}</Button>
    </div>
  </ModalShell>
}
