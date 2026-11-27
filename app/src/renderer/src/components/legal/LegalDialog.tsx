import { useRef, type ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import './legal.css'

/** Portal, focus containment/restore, scroll lock and Escape handling for long notices. */
export function LegalDialog({ open, onClose, title, children, dismissible = true }: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  dismissible?: boolean
}) {
  const { t } = useTranslation()
  const titleRef = useRef<HTMLHeadingElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)
  return (
    <Dialog.Root open={open} onOpenChange={value => { if (!value && dismissible) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="legal-dialog-overlay" />
        <Dialog.Content className="legal-dialog" aria-describedby={undefined}
          onOpenAutoFocus={event => { event.preventDefault(); returnFocus.current = document.activeElement as HTMLElement; titleRef.current?.focus() }}
          onCloseAutoFocus={event => { event.preventDefault(); if (returnFocus.current?.isConnected) returnFocus.current.focus() }}
          onPointerDownOutside={event => event.preventDefault()}
          onEscapeKeyDown={event => { if (!dismissible) event.preventDefault() }}>
          <div className="legal-dialog-heading"><Dialog.Title ref={titleRef} tabIndex={-1}>{title}</Dialog.Title>{dismissible && <Dialog.Close className="legal-dialog-close" aria-label={t('common.close')}><X size={20} /></Dialog.Close>}</div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
