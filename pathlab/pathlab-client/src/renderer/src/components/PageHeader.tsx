import React from 'react'

interface PageHeaderProps {
  title: string
  description?: React.ReactNode
  children?: React.ReactNode
  className?: string
}

export function PageHeader({ title, description, children, className }: PageHeaderProps) {
  return (
    <div
      data-page-header="true"
      className={`flex flex-col gap-4 border-b border-[color:var(--surface-border)] pb-5 md:flex-row md:items-end md:justify-between ${className || 'mb-8'}`}
    >
      <div className="min-w-0 space-y-2">
        <h1 className="text-[1.85rem] font-semibold leading-tight tracking-[-0.035em] text-slate-950 sm:text-[2.35rem]">{title}</h1>
        {description && <p className="max-w-3xl text-sm leading-7 text-slate-500 sm:text-base">{description}</p>}
      </div>
      {children && <div data-page-header-actions="true" className="flex flex-wrap items-center gap-3">{children}</div>}
    </div>
  )
}
