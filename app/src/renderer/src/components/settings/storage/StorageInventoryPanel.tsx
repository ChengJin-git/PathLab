import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ChevronLeft, ChevronRight, File, Folder, HardDrive, Loader2, RefreshCw, Trash2, X } from 'lucide-react'
import { Card } from '../../ui/card'
import { Button } from '../../ui/button'
import { Checkbox } from '../../ui/checkbox'
import { Select } from '../../ui/select'
import { formatFileSize } from '../../../lib/utils/utils'
import { ShowConfirmDialog } from '../ConfirmDialog'
import { StorageSelectionControl } from './StorageSelectionControl'
import {
  getStorageInventory, scanStorageInventory, getInventoryItems, cleanStorageInventory,
  cancelInventoryOperation,
  type StorageInventory, type InventoryPage, type InventoryOperation, type InventoryItem,
  type InventorySelection, type StorageItemState,
} from '../../../api/storage'

interface SelectionState {
  key: string
  all: boolean
  // Explicit selections or exclusions, never the entire filtered inventory.
  items: Map<string, number>
}
const SELECTION_LIMIT = 1000
const STATES: StorageItemState[] = ['orphaned', 'cached', 'referenced', 'recent', 'managed']

export function StorageInventoryPanel({ showConfirmDialog, closeConfirmDialog }: {
  showConfirmDialog: ShowConfirmDialog; closeConfirmDialog: () => void
}) {
  const { t } = useTranslation()
  const tr = (key: string, values: Record<string, unknown> = {}) => t(`settings.storageInventory.${key}`, values)
  const [data, setData] = useState<StorageInventory | null>(null)
  const [loadedPage, setLoadedPage] = useState<{ key: string; value: InventoryPage } | null>(null)
  const [category, setCategory] = useState('')
  const [state, setState] = useState<StorageItemState>('orphaned')
  const [pagination, setPagination] = useState<{ key: string; cursors: string[] }>({ key: '', cursors: [] })
  const [selection, setSelection] = useState<SelectionState>({ key: '', all: false, items: new Map() })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [pageFailure, setPageFailure] = useState<string | null>(null)
  const [pageReload, setPageReload] = useState(0)
  const requestLock = useRef(false)
  const list = useRef<HTMLDivElement>(null)
  const operation = data?.operation
  const busy = !!operation && ['pending', 'processing', 'failed'].includes(operation.status)
  const scopeKey = JSON.stringify([data?.generation, data?.scanned_at, category, state])
  const cursors = pagination.key === scopeKey ? pagination.cursors : []
  const cursor = cursors.at(-1)
  const pageKey = JSON.stringify([scopeKey, cursor])
  const pageError = pageFailure === pageKey
  const page = loadedPage?.key === pageKey ? loadedPage.value : null
  const loading = !!data?.generation && !page && !pageError
  const currentSelection = useMemo(() => selection.key === scopeKey ? selection : {
    key: scopeKey, all: false, items: new Map<string, number>(),
  }, [selection, scopeKey])
  const canClean = state === 'orphaned' || state === 'cached'
  const ready = !!page && page.generation === data?.generation
  const filteredCategories = data?.categories.filter(item => !category || item.category === category) ?? []
  const total = page?.total ?? filteredCategories.reduce((sum, item) => sum + item.states[state].items, 0)
  const filteredSize = page?.allocated ?? filteredCategories.reduce((sum, item) => sum + item.states[state].allocated, 0)
  const selectedCount = currentSelection.all ? Math.max(0, total - currentSelection.items.size) : currentSelection.items.size
  const itemSizes = [...currentSelection.items.values()].reduce((sum, size) => sum + size, 0)
  const selectedSize = currentSelection.all ? Math.max(0, filteredSize - itemSizes) : itemSizes
  const isSelected = (id: string) => currentSelection.all ? !currentSelection.items.has(id) : currentSelection.items.has(id)
  const pageSelected = page?.items.filter(item => isSelected(item.id)).length ?? 0
  const disabled = !ready || busy || submitting || !page?.items.length
  const reclaimable = data?.categories.reduce((sum, item) => sum + item.reclaimable, 0) ?? 0

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      try {
        const next = await getStorageInventory(controller.signal)
        if (controller.signal.aborted) return
        setData(next)
        if (next.operation && ['pending', 'processing', 'failed'].includes(next.operation.status)) timer = setTimeout(refresh, 2000)
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : tr('loadFailed'))
      }
    }
    void refresh()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [operation?.id, operation?.status])

  useEffect(() => {
    if (!data?.generation) return
    const controller = new AbortController()
    setPageFailure(null)
    void getInventoryItems(category, state, cursor, controller.signal).then(value => {
      if (controller.signal.aborted) return
      if (value.generation !== data.generation) {
        // A scan finished between the summary and page request; invalidate the
        // old selection rather than applying it to another generation.
        void getStorageInventory(controller.signal).then(setData).catch(() => {})
        return
      }
      setLoadedPage({ key: pageKey, value })
      list.current?.scrollTo?.({ top: 0 })
    }).catch(() => {
      if (!controller.signal.aborted) setPageFailure(pageKey)
    })
    return () => controller.abort()
  }, [category, state, cursor, data?.generation, data?.scanned_at, pageKey, pageReload])

  const clearSelection = () => setSelection({ key: scopeKey, all: false, items: new Map() })
  const chooseCategory = (value: string) => {
    clearSelection(); setPagination({ key: '', cursors: [] }); setCategory(value)
  }
  const chooseState = (value: string) => {
    clearSelection(); setPagination({ key: '', cursors: [] }); setState(value as StorageItemState)
  }
  const setItemsSelected = (items: InventoryItem[], checked: boolean) => {
    const next = new Map(currentSelection.items)
    for (const item of items) {
      if (checked !== currentSelection.all) next.set(item.id, item.allocated)
      else next.delete(item.id)
    }
    if (next.size > SELECTION_LIMIT) { setError(tr('selectionLimit')); return }
    setSelection({ ...currentSelection, items: next })
  }
  const run = async (action: () => Promise<InventoryOperation>) => {
    if (requestLock.current) return
    requestLock.current = true; setSubmitting(true); setError('')
    try {
      const result = await action()
      setData(previous => previous ? { ...previous, operation: result } : {
        generation: null, scanned_at: null, size: 0, allocated: 0, files: 0, links: 0, categories: [], operation: result,
      })
      clearSelection()
    } catch (err) { setError(err instanceof Error ? err.message : tr('loadFailed')) }
    finally { requestLock.current = false; setSubmitting(false) }
  }

  const clean = () => {
    if (!data?.generation || !canClean || !ready || !selectedCount || busy || submitting) return
    const filter = { generation: data.generation, category: category || undefined, state: state as 'orphaned' | 'cached' }
    const request: InventorySelection = currentSelection.all
      ? { ...filter, scope: 'all', excluded_ids: [...currentSelection.items.keys()] }
      : { ...filter, scope: 'selected', ids: [...currentSelection.items.keys()] }
    const detail = tr(currentSelection.all ? 'confirmAll' : 'confirmSelected', {
      count: selectedCount.toLocaleString(), size: formatFileSize(selectedSize),
      group: category ? tr(`categories.${category}`) : tr('allCategories'), state: tr(`states.${state}`),
    })
    showConfirmDialog({ title: tr('cleanupTitle'), message: `${detail} ${tr(state === 'cached' ? 'cacheConfirm' : 'orphanConfirm')}`,
      confirmText: tr('cleanup'), confirmVariant: 'danger', onConfirm: () => {
        closeConfirmDialog(); void run(() => cleanStorageInventory(request))
      } })
  }

  return <Card className="mb-6 overflow-hidden p-0" data-storage-inventory>
    <div className="px-4 pt-5 sm:px-6 sm:pt-6">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight text-slate-900"><HardDrive className="h-[18px] w-[18px] text-slate-500" />{tr('title')}</h2>
          <p className="mt-1.5 text-xs text-slate-500">{data?.scanned_at ? tr('updated', { time: new Date(data.scanned_at * 1000).toLocaleString() }) : tr('description')}</p>
        </div>
        <Button variant="outline" size="sm" className="shrink-0 gap-1.5 shadow-none" disabled={busy || submitting} onClick={() => void run(scanStorageInventory)}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{tr('scan')}
        </Button>
      </div>
      {error && <p role="alert" className="mb-3 text-sm text-red-600">{error}</p>}
      {operation?.status === 'cancelled' && operation.error && <p role="alert" className="mb-3 text-sm text-slate-600">{operation.error}</p>}
      {busy && <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-100 bg-slate-50/80 px-3 py-2.5 text-xs text-slate-600">
        <span className="flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />{operation?.status === 'failed' ? operation.error : operation && operation.processed > 0 ? tr('working', { count: operation.processed.toLocaleString(), stage: tr(`stages.${operation.result?.stage ?? 'queued'}`) }) : tr(`stages.${operation?.result?.stage ?? 'queued'}`)}</span>
        <button className="rounded px-1 py-0.5 font-medium text-slate-700 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 disabled:opacity-50" disabled={submitting} onClick={() => operation && void run(() => cancelInventoryOperation(operation.id))}>{tr('stop')}</button>
      </div>}
      {operation?.status === 'completed' && operation.result?.freed !== undefined && <p role="status" className="mb-4 flex items-center gap-1.5 text-xs text-slate-600"><Check className="h-3.5 w-3.5" />{tr('completed', { size: formatFileSize(operation.result.freed), count: operation.result.deleted, skipped: operation.result.skipped })}</p>}
      {data?.generation && <>
        <div className="mb-5 grid grid-cols-2 divide-x divide-slate-200/80 rounded-xl border border-slate-100 bg-slate-50/60 py-4">
          <div className="min-w-0 px-4"><p className="text-xs text-slate-500">{tr('used')}</p><p className="mt-1.5 text-xl font-semibold tracking-tight tabular-nums text-slate-900 sm:text-2xl">{formatFileSize(data.allocated)}</p></div>
          <div className="min-w-0 px-4"><p className="text-xs text-slate-500">{tr('reclaimable')}</p><p className="mt-1.5 text-xl font-semibold tracking-tight tabular-nums text-slate-900 sm:text-2xl">{formatFileSize(reclaimable)}</p></div>
        </div>
        <div className="mb-5">
          <div className="grid grid-cols-[minmax(0,1fr)_5.5rem_5.5rem] gap-2 px-2 pb-2 text-[11px] text-slate-500 sm:grid-cols-[minmax(0,1fr)_8rem_8rem] sm:gap-4">
            <span>{tr('categoryHeading')}</span><span className="text-right">{tr('used')}</span><span className="text-right">{tr('reclaimable')}</span>
          </div>
          {[...data.categories].sort((a, b) => b.allocated - a.allocated).map(item => <button key={item.category} type="button"
            onClick={() => chooseCategory(category === item.category ? '' : item.category)} aria-pressed={category === item.category}
            aria-label={tr(`categories.${item.category}`)}
            className={`group grid w-full grid-cols-[minmax(0,1fr)_5.5rem_5.5rem] items-center gap-2 rounded-lg px-2 py-2.5 text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 sm:grid-cols-[minmax(0,1fr)_8rem_8rem] sm:gap-4 ${category === item.category ? 'bg-primary-50/70 text-primary-900' : 'text-slate-700 hover:bg-slate-50'}`}>
            <span className="min-w-0 sm:flex sm:items-center sm:gap-2.5"><span className="flex min-w-0 items-center gap-2"><span className="truncate font-medium">{tr(`categories.${item.category}`)}</span>{category === item.category && <Check className="h-3 w-3 shrink-0 text-primary-600" />}</span>
              <span className="mt-1 block text-[10px] tabular-nums text-slate-500 sm:mt-0">{tr('fileCount', { count: item.files.toLocaleString() })}</span>
            </span>
            <span className="whitespace-nowrap text-right tabular-nums">{formatFileSize(item.allocated)}</span>
            <span className="whitespace-nowrap text-right tabular-nums text-slate-500">{item.reclaimable ? formatFileSize(item.reclaimable) : '—'}</span>
          </button>)}
        </div>
      </>}
    </div>

    {data?.generation ? <>
      <div className="border-t border-slate-100 px-4 pt-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Select ariaLabel={tr('filter')} value={state} onChange={chooseState}
              options={STATES.map(value => ({ value, label: tr(`states.${value}`) }))}
              className="w-40" triggerClassName="h-9 min-h-9 rounded-lg px-3 py-1.5 text-xs" dropdownClassName="min-w-48" />
            {category && <button type="button" onClick={() => chooseCategory('')} aria-label={tr('clearCategory')}
              className="inline-flex min-w-0 items-center gap-1.5 rounded-md bg-slate-100 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-200/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
              <span className="max-w-28 truncate">{tr(`categories.${category}`)}</span><X className="h-3 w-3 shrink-0" />
            </button>}
          </div>
          {canClean && <Button variant="outline" size="sm" className="gap-1.5 shadow-none" disabled={disabled || !selectedCount} onClick={clean}>
            <Trash2 className="h-3.5 w-3.5" />{currentSelection.all && selectedCount ? tr('cleanAllSelected') : tr('cleanup')}
          </Button>}
        </div>
        <p className="mb-4 mt-2.5 text-xs leading-relaxed text-slate-500">{tr(`hints.${state}`)}</p>
        <div className="flex min-h-12 items-center gap-3 border-y border-slate-100 py-2">
          {canClean && <StorageSelectionControl checked={!!page?.items.length && pageSelected === page.items.length}
            indeterminate={pageSelected > 0 && pageSelected < (page?.items.length ?? 0)} disabled={!!disabled}
            pageLabel={tr('selectPage')} menuLabel={tr('selectionMenu')} pageCount={String(page?.items.length ?? 0)}
            allLabel={tr('selectAll')} totalCount={total.toLocaleString()} clearLabel={tr('clearSelection')}
            hasSelection={selectedCount > 0} onClear={clearSelection}
            onTogglePage={() => setItemsSelected(page?.items ?? [], pageSelected !== page?.items.length)}
            onSelectPage={() => setSelection({ key: scopeKey, all: false, items: new Map(page?.items.map(item => [item.id, item.allocated])) })}
            onSelectAll={() => setSelection({ key: scopeKey, all: true, items: new Map() })} />}
          <div className="min-w-0 flex-1" aria-live="polite" data-storage-selection>
            <p className={`text-xs ${selectedCount ? 'font-medium text-slate-800' : 'text-slate-500'}`}>
              {selectedCount ? tr(currentSelection.all ? 'allSelectedCount' : 'selectedCount', { count: selectedCount.toLocaleString() }) : tr('resultCount', { count: total.toLocaleString() })}
            </p>
            {selectedCount > 0 && <p className="mt-0.5 text-[11px] text-slate-500">{currentSelection.all ? tr('selectionScope') : tr('selectedSize', { size: formatFileSize(selectedSize) })}</p>}
          </div>
          <span className="shrink-0 pr-1 text-[11px] text-slate-500">{tr('used')}</span>
        </div>
      </div>
      <div ref={list} aria-busy={loading} className="max-h-[26rem] min-h-28 overflow-y-auto overscroll-contain px-4 sm:px-6">
        {loading ? <div className="flex justify-center py-10"><Loader2 aria-label={tr('loading')} className="h-5 w-5 animate-spin text-slate-400" /></div> : pageError ? <div role="alert" className="flex min-h-28 items-center justify-center gap-3 py-6 text-sm text-slate-600">
          <span>{tr('listLoadFailed')}</span>
          <button type="button" className="rounded px-1 py-0.5 text-primary-700 underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
            onClick={() => { setPageFailure(null); setPageReload(value => value + 1) }}>{tr('retry')}</button>
        </div> : page?.items.map(item => {
          const checked = canClean && isSelected(item.id)
          const name = item.path.split('/').at(-1)
          const parent = item.path.slice(0, item.path.lastIndexOf('/'))
          const Icon = item.files + item.links > 1 ? Folder : File
          return <label key={item.id} data-storage-file-row className={`flex items-center gap-3 border-b border-slate-100/80 px-1 py-3 transition-colors ${canClean ? 'cursor-pointer' : ''} ${checked ? 'bg-primary-50/40' : 'hover:bg-slate-50/60'}`}>
            {canClean && <Checkbox aria-label={tr('select', { path: item.path })} checked={checked} disabled={busy || submitting}
              onChange={() => setItemsSelected([item], !checked)} />}
            <Icon className="hidden h-4 w-4 shrink-0 text-slate-400 sm:block" aria-hidden="true" />
            <div className="min-w-0 flex-1" title={item.path}><p className="truncate text-xs font-medium text-slate-700">{name}</p>
              <p className="mt-1 truncate text-[11px] text-slate-500">{parent}{item.files + item.links > 1 && ` · ${tr('itemCount', { files: item.files.toLocaleString(), links: item.links.toLocaleString() })}`}</p>
            </div>
            <span className="shrink-0 text-xs tabular-nums text-slate-600">{formatFileSize(item.allocated)}</span>
          </label>
        })}
        {!loading && !pageError && !page?.items.length && <p className="py-10 text-center text-sm text-slate-500">{tr('empty')}</p>}
      </div>
      {ready && !pageError && page.items.length > 0 && <div data-storage-pagination className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 sm:px-6">
        <span className="text-[11px] tabular-nums text-slate-500">{tr('pageRange', { start: cursors.length * 50 + 1, end: Math.min(cursors.length * 50 + page.items.length, total), total: total.toLocaleString() })}</span>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label={tr('previous')} disabled={!cursors.length || loading} className="h-8 w-8" onClick={() => setPagination({ key: scopeKey, cursors: cursors.slice(0, -1) })}><ChevronLeft className="h-4 w-4" /></Button>
          <span className="min-w-7 text-center text-xs tabular-nums text-slate-600">{cursors.length + 1}</span>
          <Button variant="ghost" size="icon" aria-label={tr('next')} disabled={!page?.next_cursor || loading} className="h-8 w-8" onClick={() => page?.next_cursor && setPagination({ key: scopeKey, cursors: [...cursors, page.next_cursor] })}><ChevronRight className="h-4 w-4" /></Button>
        </div>
      </div>}
    </> : !busy && <p className="px-4 py-10 text-center text-sm text-slate-500">{tr('start')}</p>}

  </Card>
}
