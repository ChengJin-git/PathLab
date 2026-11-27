import { useId, useRef, useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { ChevronDown } from 'lucide-react'
import { Checkbox } from '../../ui/checkbox'

interface Props {
  checked: boolean
  indeterminate: boolean
  disabled: boolean
  pageLabel: string
  menuLabel: string
  pageCount: string
  allLabel: string
  totalCount: string
  clearLabel: string
  hasSelection: boolean
  onTogglePage: () => void
  onSelectPage: () => void
  onSelectAll: () => void
  onClear: () => void
}

/** A page checkbox with one adjacent menu for the two bulk-selection scopes. */
export function StorageSelectionControl(props: Props) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const id = useId()
  const choose = (action: () => void) => {
    action()
    setOpen(false)
    trigger.current?.focus()
  }
  return <div className="inline-flex h-9 shrink-0 items-center rounded-lg border border-slate-200 bg-white">
    <label className="flex h-full cursor-pointer items-center pl-2.5 pr-2">
      <Checkbox checked={props.checked} indeterminate={props.indeterminate} disabled={props.disabled}
        aria-label={props.pageLabel} onChange={props.onTogglePage} />
    </label>
    <Popover.Root open={open && !props.disabled} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button ref={trigger} type="button" aria-label={props.menuLabel} title={props.menuLabel}
          aria-haspopup="menu" aria-expanded={open && !props.disabled} aria-controls={open ? id : undefined}
          disabled={props.disabled} onKeyDown={event => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setOpen(true) }
          }} className="flex h-full w-7 items-center justify-center rounded-r-lg border-l border-slate-100 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 disabled:opacity-40">
          <ChevronDown size={13} aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content ref={menu} id={id} role="menu" aria-label={props.menuLabel} align="start" sideOffset={6}
          collisionPadding={12} className="pathlab-select-menu w-60"
          onOpenAutoFocus={event => { event.preventDefault(); menu.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus() }}
          onEscapeKeyDown={() => trigger.current?.focus()}
          onKeyDown={event => {
            if (event.key === 'Tab') { setOpen(false); return }
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
            event.preventDefault()
            const options = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
            const index = options.indexOf(document.activeElement as HTMLButtonElement)
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
            options[next]?.focus()
          }}>
          <button type="button" role="menuitem" className="pathlab-select-option" onClick={() => choose(props.onSelectPage)}>
            <span>{props.pageLabel}</span><span className="text-xs tabular-nums text-slate-400">{props.pageCount}</span>
          </button>
          <button type="button" role="menuitem" className="pathlab-select-option" onClick={() => choose(props.onSelectAll)}>
            <span>{props.allLabel}</span><span className="text-xs tabular-nums text-slate-400">{props.totalCount}</span>
          </button>
          {props.hasSelection && <>
            <div role="separator" className="my-1 border-t border-slate-100" />
            <button type="button" role="menuitem" className="pathlab-select-option" onClick={() => choose(props.onClear)}>{props.clearLabel}</button>
          </>}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  </div>
}
