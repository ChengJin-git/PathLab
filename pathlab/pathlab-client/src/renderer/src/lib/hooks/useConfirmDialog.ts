import { useState } from 'react'
import type { ConfirmDialogState, ShowConfirmDialog } from '../../components/settings/ConfirmDialog'

const CLOSED: ConfirmDialogState = {
  isOpen: false,
  title: '',
  message: '',
  onConfirm: () => {},
}

export function useConfirmDialog() {
  const [dialogState, setDialogState] = useState<ConfirmDialogState>(CLOSED)

  const showConfirmDialog: ShowConfirmDialog = (config) => {
    setDialogState({ isOpen: true, ...config })
  }

  const closeConfirmDialog = () => {
    setDialogState(CLOSED)
  }

  return { dialogState, showConfirmDialog, closeConfirmDialog }
}
