import { useState, type ReactNode } from 'react'
import { PanelRightOpen, X } from 'lucide-react'
import { Button } from '../ui/button'
import { cn } from '../../lib/utils'

interface RunWorkspaceLayoutProps {
  left: ReactNode
  main: ReactNode
  right: ReactNode
  className?: string
}

export function RunWorkspaceLayout({ left, main, right, className }: RunWorkspaceLayoutProps) {
  const [rightOpen, setRightOpen] = useState(false)

  return (
    <div className={cn('relative grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)_320px]', className)}>
      <aside className="min-w-0 xl:sticky xl:top-4 xl:self-start">{left}</aside>

      <main className="min-w-0 space-y-3">
        <div className="hidden justify-end md:flex xl:hidden">
          <Button variant="outline" size="sm" className="gap-2" onClick={() => setRightOpen(true)}>
            <PanelRightOpen className="h-4 w-4" />
            Run panel
          </Button>
        </div>
        {main}
      </main>

      <aside className="min-w-0 md:hidden xl:sticky xl:top-4 xl:block xl:self-start">{right}</aside>

      {rightOpen ? (
        <div className="fixed inset-0 z-40 hidden md:block xl:hidden">
          <button
            type="button"
            aria-label="Close run panel"
            className="absolute inset-0 bg-slate-950/30 backdrop-blur-sm"
            onClick={() => setRightOpen(false)}
          />
          <div className="absolute right-0 top-0 h-full w-full max-w-sm overflow-y-auto border-l border-slate-200 bg-white p-4 shadow-2xl">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Run context</div>
                <div className="text-lg font-semibold text-slate-950">Side panel</div>
              </div>
              <Button variant="ghost" size="icon" aria-label="Close run panel" onClick={() => setRightOpen(false)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
            {right}
          </div>
        </div>
      ) : null}
    </div>
  )
}
