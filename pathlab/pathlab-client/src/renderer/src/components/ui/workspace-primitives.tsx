import React from 'react'
import { Search } from 'lucide-react'

import { cn } from '../../lib/utils'
import { Card } from './card'
import { Input } from './input'

type AccentTone = 'neutral' | 'system' | 'success' | 'danger' | 'pathology'

const accentStyles: Record<AccentTone, string> = {
  neutral: 'data-[accent=neutral]:border-[color:var(--surface-border)] data-[accent=neutral]:bg-[color:var(--surface-work)]',
  system: 'data-[accent=system]:border-primary-200/80 data-[accent=system]:bg-primary-50/60',
  success: 'data-[accent=success]:border-emerald-200/80 data-[accent=success]:bg-emerald-50/70',
  danger: 'data-[accent=danger]:border-red-200/80 data-[accent=danger]:bg-red-50/70',
  pathology: 'data-[accent=pathology]:border-secondary-200/80 data-[accent=pathology]:bg-secondary-50/70',
}

interface WorkspaceStatCardProps {
  label: string
  value: React.ReactNode
  accent?: AccentTone
  detail?: React.ReactNode
  className?: string
}

export function WorkspaceStatCard({
  label,
  value,
  accent = 'neutral',
  detail,
  className,
}: WorkspaceStatCardProps) {
  return (
    <Card
      data-testid="workspace-stat-card"
      data-accent={accent}
      surface="work"
      className={cn(
        'overflow-visible p-4 sm:p-6',
        accentStyles[accent],
        className,
      )}
    >
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
      <div className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-4xl">{value}</div>
      {detail ? <div className="mt-2 text-xs text-slate-500">{detail}</div> : null}
    </Card>
  )
}

interface SegmentedControlOption {
  value: string
  label: string
}

interface SegmentedControlProps {
  value: string
  onChange: (value: string) => void
  options: readonly SegmentedControlOption[]
  className?: string
}

export function SegmentedControl({ value, onChange, options, className }: SegmentedControlProps) {
  return (
    <div className={cn('flex items-center gap-1 rounded-full border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] p-1 shadow-[var(--shadow-soft)]', className)}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            data-state={active ? 'active' : 'inactive'}
            onClick={() => onChange(option.value)}
            className={cn(
              'rounded-full px-4 py-2 text-sm font-medium transition-colors',
              active
                ? 'bg-slate-900 text-white shadow-[var(--shadow-soft)]'
                : 'text-slate-500 hover:bg-white/90 hover:text-slate-950',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

interface EmptyStatePanelProps {
  title: string
  description: string
  tone?: AccentTone
  icon?: React.ReactNode
  action?: React.ReactNode
  className?: string
}

export function EmptyStatePanel({
  title,
  description,
  tone = 'neutral',
  icon,
  action,
  className,
}: EmptyStatePanelProps) {
  return (
    <Card
      data-testid="workspace-empty-state"
      data-tone={tone}
      surface="work"
      className={cn(
        'flex flex-col items-center justify-center p-12 text-center',
        accentStyles[tone].replaceAll('accent', 'tone'),
        className,
      )}
    >
      {icon ? <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-[color:var(--surface-muted)] text-slate-400">{icon}</div> : null}
      <h3 className="text-lg font-semibold tracking-[-0.02em] text-slate-950">{title}</h3>
      <p className="mt-2 max-w-md text-sm leading-7 text-slate-500">{description}</p>
      {action ? <div className="mt-6">{action}</div> : null}
    </Card>
  )
}

interface SearchFieldProps {
  value: string
  onChange: (value: string) => void
  placeholder: string
  clearButton?: React.ReactNode
  className?: string
}

export function SearchField({ value, onChange, placeholder, clearButton, className }: SearchFieldProps) {
  return (
    <div
      data-testid="workspace-search-field"
      data-search-field="true"
      className={cn('relative mx-auto w-full max-w-2xl', className)}
    >
      <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 sm:h-5 sm:w-5" />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="pl-11 pr-10 sm:pl-12"
      />
      {clearButton ? <div className="absolute right-3 top-1/2 -translate-y-1/2">{clearButton}</div> : null}
    </div>
  )
}
