import React from 'react'
import { cn } from '../lib/utils'

interface PageHeaderProps {
  title: string
  description?: React.ReactNode
  children?: React.ReactNode
  className?: string
  titleClassName?: string
  contentClassName?: string
  actionsClassName?: string
}

export function PageHeader({ title, description, children, className, titleClassName, contentClassName, actionsClassName }: PageHeaderProps) {
  return (
    <div
      data-page-header="true"
      className={cn('flex flex-col gap-4 border-b border-[color:var(--surface-border)] pt-2 pb-4 md:flex-row md:items-start md:justify-between', className || 'mb-4')}
    >
      <div className={cn('min-w-0 space-y-2', contentClassName)}>
        <h1 className={cn('text-[1.85rem] font-semibold leading-tight tracking-[-0.035em] text-slate-950 sm:text-[2.35rem]', titleClassName)}>{title}</h1>
        {description && <p className="max-w-3xl text-sm leading-7 text-slate-500 sm:text-base">{description}</p>}
      </div>
      {children && <div data-page-header-actions="true" className={cn('flex flex-wrap items-center gap-3', actionsClassName)}>{children}</div>}
    </div>
  )
}
