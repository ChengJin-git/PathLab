import { Trash2, Info } from 'lucide-react'
import { Button } from '../ui/button'

export interface ConfirmDialogState {
  isOpen: boolean
  title: string
  message: string
  onConfirm: () => void
  confirmText?: string
  confirmVariant?: 'danger' | 'warning' | 'info'
  showCancel?: boolean
}

export type ShowConfirmDialog = (config: Omit<ConfirmDialogState, 'isOpen'>) => void

export interface ConfirmDialogProps {
  dialog: ConfirmDialogState
  onClose: () => void
}

export function ConfirmDialog({ dialog, onClose }: ConfirmDialogProps) {
  if (!dialog.isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <div className="text-center mb-6">
          <div className={`w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4 ${
            dialog.confirmVariant === 'danger' ? 'bg-red-100' :
            dialog.confirmVariant === 'info' ? 'bg-primary-100' : 'bg-amber-100'
          }`}>
            {dialog.confirmVariant === 'danger' ? (
              <Trash2 className="w-7 h-7 text-red-600" />
            ) : dialog.confirmVariant === 'info' ? (
              <Info className="w-7 h-7 text-primary-600" />
            ) : (
              <Trash2 className="w-7 h-7 text-amber-600" />
            )}
          </div>
          <h3 className="text-lg font-semibold text-gray-900 mb-2">{dialog.title}</h3>
          <p className="text-gray-600 text-sm">{dialog.message}</p>
        </div>
        <div className="flex gap-3">
          {dialog.showCancel !== false && (
            <Button
              variant="outline"
              className="flex-1"
              onClick={onClose}
            >
              Cancel
            </Button>
          )}
          <Button
            className={`flex-1 ${
              dialog.confirmVariant === 'danger'
                ? 'bg-red-600 hover:bg-red-700 text-white'
                : dialog.confirmVariant === 'info'
                  ? 'bg-primary-600 hover:bg-primary-700 text-white'
                  : 'bg-amber-600 hover:bg-amber-700 text-white'
            }`}
            onClick={dialog.onConfirm}
          >
            {dialog.confirmText || 'Confirm'}
          </Button>
        </div>
      </div>
    </div>
  )
}

