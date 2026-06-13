import React, { useEffect } from 'react'
import { cn } from '../../lib/utils'

interface ModalShellProps {
  isOpen: boolean
  onClose?: () => void
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '6xl'
  className?: string
  children: React.ReactNode
}

const MAX_WIDTH: Record<string, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '6xl': 'max-w-6xl',
}

export function ModalShell({
  isOpen,
  onClose,
  maxWidth = 'md',
  className,
  children,
}: ModalShellProps) {
  useEffect(() => {
    if (!onClose) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  if (!isOpen) return null

  return (
    <button
      type="button"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-2 sm:p-4 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        role="dialog"
        className={cn(
          'bg-white rounded-xl sm:rounded-2xl shadow-2xl w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto',
          MAX_WIDTH[maxWidth] ?? 'max-w-md',
          className
        )}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </button>
  )
}
