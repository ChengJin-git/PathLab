import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Checkbox } from '../ui/checkbox'
import { useTranslation } from 'react-i18next'
import * as Dialog from '@radix-ui/react-dialog'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Search,
  X,
} from 'lucide-react'
import {
  archiveWorkspace,
  findWorkspaceDatasets,
  saveWorkspace,
  type Workspace,
  type WorkspaceCapabilities,
  type WorkspaceDataset,
} from '../../api/workspaces'
import type { ExecutionMode } from '../../lib/workspaceSelection'

interface Props {
  workspace?: Workspace
  capabilities: WorkspaceCapabilities
  onClose: () => void
  onSaved: (workspace: Workspace) => void
  onArchived: (id: string) => void
  onCloseAutoFocus: () => void
}

const inputClass =
  'w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100'

export function WorkspaceEditor({
  workspace,
  capabilities,
  onClose,
  onSaved,
  onArchived,
  onCloseAutoFocus,
}: Props) {
  const { t, i18n } = useTranslation()
  const [name, setName] = useState(workspace?.name ?? '')
  const [selected, setSelected] = useState(workspace?.dataset_ids ?? [])
  const [mode, setMode] = useState<ExecutionMode>(
    workspace?.execution_mode ?? 'standard',
  )
  const [skills, setSkills] = useState(
    workspace?.enabled_skills ?? capabilities.skills.map((item) => item.id),
  )
  const [connectors, setConnectors] = useState(
    workspace?.enabled_connectors ??
      capabilities.connectors.map((item) => item.id),
  )
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [datasets, setDatasets] = useState<WorkspaceDataset[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const nameRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let live = true
    setLoading(true)
    const timer = setTimeout(() => {
      findWorkspaceDatasets(search, page)
        .then((result) => {
          if (live) {
            setDatasets(result.items)
            setTotal(result.total)
          }
        })
        .catch((err) => live && setError(err.message))
        .finally(() => live && setLoading(false))
    }, 200)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [search, page])

  const persist = async (event: FormEvent) => {
    event.preventDefault()
    event.stopPropagation()
    if (saving || !name.trim()) return
    setSaving(true)
    setError('')
    try {
      onSaved(
        await saveWorkspace(
          {
            name: name.trim(),
            dataset_ids: selected,
            root_paths: workspace?.root_paths ?? [],
            enabled_skills: skills,
            enabled_connectors: connectors,
            execution_mode: mode,
          },
          workspace?.workspace_id,
        ),
      )
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const archive = async () => {
    if (!workspace || saving) return
    setSaving(true)
    setError('')
    try {
      await archiveWorkspace(workspace.workspace_id)
      onArchived(workspace.workspace_id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !saving) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[70] bg-black/30" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-[71] w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl outline-none"
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            nameRef.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            onCloseAutoFocus()
          }}
          onEscapeKeyDown={(event) => {
            if (saving) event.preventDefault()
          }}
          onInteractOutside={(event) => {
            if (saving) event.preventDefault()
          }}
        >
          <form onSubmit={persist} className="flex max-h-[85dvh] flex-col">
            <div className="px-5 pb-4 pt-5">
              <Dialog.Title className="text-base font-semibold text-gray-900">
                {t(
                  workspace
                    ? 'aiChat.workspaceControls.manage'
                    : 'aiChat.newWorkspace',
                )}
              </Dialog.Title>
              <Dialog.Description className="mt-1.5 text-sm text-gray-500">
                {t('aiChat.workspaceControls.editorHint')}
              </Dialog.Description>
              <Dialog.Close asChild>
                <button
                  type="button"
                  disabled={saving}
                  aria-label={t('common.close')}
                  className="absolute right-4 top-4 cursor-pointer rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/30"
                >
                  <X className="h-4 w-4" />
                </button>
              </Dialog.Close>
            </div>
            <fieldset
              disabled={saving}
              className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-5 pb-5 disabled:opacity-70"
            >
              <label className="block text-sm font-medium text-gray-700">
                {t('aiChat.workspaceControls.name')}
                <input
                  ref={nameRef}
                  value={name}
                  maxLength={120}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t('aiChat.workspaceNamePlaceholder')}
                  className={`${inputClass} mt-1.5 font-normal`}
                />
              </label>
              <section aria-label={t('aiChat.workspaceControls.datasets')}>
                <div className="mb-2 flex items-center justify-between text-sm">
                  <span className="font-medium text-gray-700">
                    {t('aiChat.workspaceControls.datasets')}
                  </span>
                  <span className="text-xs text-gray-500">
                    {t('aiChat.workspaceControls.selected', {
                      count: selected.length,
                    })}
                  </span>
                </div>
                <div className="overflow-hidden rounded-xl border border-gray-200">
                  <div className="flex items-center gap-2 border-b border-gray-100 px-3 py-2.5 focus-within:ring-2 focus-within:ring-inset focus-within:ring-primary-500/20">
                    <Search
                      className="h-4 w-4 shrink-0 text-gray-400"
                      aria-hidden
                    />
                    <input
                      value={search}
                      onChange={(event) => {
                        setSearch(event.target.value)
                        setPage(1)
                      }}
                      aria-label={t('aiChat.workspaceControls.searchDatasets')}
                      placeholder={t('aiChat.workspaceControls.searchDatasets')}
                      className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-gray-400"
                    />
                    {loading && (
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin text-gray-400"
                        aria-label={t('common.loading')}
                      />
                    )}
                  </div>
                  <div
                    className="max-h-44 min-h-16 overflow-y-auto overscroll-contain p-1"
                    aria-busy={loading}
                  >
                    {datasets.map((dataset) => (
                      <label
                        key={dataset.dataset_id}
                        className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2.5 text-sm hover:bg-gray-50"
                      >
                        <Checkbox
                          checked={selected.includes(dataset.dataset_id)}
                          onChange={(event) =>
                            setSelected((prev) =>
                              event.target.checked
                                ? [...prev, dataset.dataset_id]
                                : prev.filter(
                                    (id) => id !== dataset.dataset_id,
                                  ),
                            )
                          }
                        />
                        <span
                          className="min-w-0 flex-1 truncate text-gray-700"
                          title={dataset.name}
                        >
                          {dataset.name}
                        </span>
                        <span className="shrink-0 text-xs text-gray-400">
                          {dataset.file_count ?? 0}
                        </span>
                      </label>
                    ))}
                    {!loading && !datasets.length && (
                      <p className="px-3 py-5 text-center text-sm text-gray-500">
                        {t('aiChat.workspaceControls.noDatasets')}
                      </p>
                    )}
                  </div>
                  {total > 30 && (
                    <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-2 py-1">
                      <button
                        type="button"
                        disabled={page === 1 || loading}
                        onClick={() => setPage((p) => p - 1)}
                        aria-label={t('aiChat.workspaceControls.previous')}
                        className="cursor-pointer rounded p-1.5 hover:bg-gray-100 disabled:opacity-30"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <span className="text-xs text-gray-500">
                        {page} / {Math.ceil(total / 30)}
                      </span>
                      <button
                        type="button"
                        disabled={page * 30 >= total || loading}
                        onClick={() => setPage((p) => p + 1)}
                        aria-label={t('aiChat.workspaceControls.next')}
                        className="cursor-pointer rounded p-1.5 hover:bg-gray-100 disabled:opacity-30"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>
              </section>
              <details className="group border-t border-gray-100 pt-3">
                <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-gray-500 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/30 [&::-webkit-details-marker]:hidden">
                  <ChevronDown
                    className="h-3.5 w-3.5 transition-transform group-open:rotate-180"
                    aria-hidden
                  />
                  {t('aiChat.workspaceControls.moreSettings')}
                </summary>
                <div className="space-y-4 pt-4 text-sm">
                  <label className="flex cursor-pointer items-center justify-between gap-3 text-gray-700">
                    {t('aiChat.workspaceControls.workspaceReadOnly')}
                    <Checkbox
                      checked={mode === 'read_only'}
                      onChange={(event) =>
                        setMode(event.target.checked ? 'read_only' : 'standard')
                      }
                    />
                  </label>
                  {[
                    {
                      label: 'aiChat.sidebar.skills',
                      options: capabilities.skills,
                      enabled: skills,
                      set: setSkills,
                    },
                    {
                      label: 'aiChat.sidebar.connectors',
                      options: capabilities.connectors,
                      enabled: connectors,
                      set: setConnectors,
                    },
                  ].map((group) => (
                    <fieldset key={group.label}>
                      <legend className="mb-2 text-xs font-medium text-gray-500">
                        {t(group.label)}
                      </legend>
                      <div className="grid grid-cols-2 gap-2">
                        {group.options.map((item) => (
                          <label
                            key={item.id}
                            className="flex cursor-pointer items-center gap-2 text-xs text-gray-600"
                          >
                            <Checkbox
                              checked={group.enabled.includes(item.id)}
                              onChange={(event) =>
                                group.set((prev) =>
                                  event.target.checked
                                    ? [...prev, item.id]
                                    : prev.filter((id) => id !== item.id),
                                )
                              }
                            />
                            {i18n.language.startsWith('zh')
                              ? item.name
                              : item.name_en}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ))}
                  {workspace && (
                    <button
                      type="button"
                      onClick={() => void archive()}
                      className="cursor-pointer text-xs text-red-600 hover:text-red-700"
                    >
                      {t('aiChat.workspaceControls.archive')}
                    </button>
                  )}
                </div>
              </details>
              {error && (
                <p role="alert" className="text-xs text-red-600">
                  {error}
                </p>
              )}
            </fieldset>
            <div className="flex shrink-0 justify-end gap-2 border-t border-gray-100 px-5 py-3.5">
              <Dialog.Close asChild>
                <button
                  type="button"
                  disabled={saving}
                  className="cursor-pointer rounded-xl px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
                >
                  {t('common.cancel')}
                </button>
              </Dialog.Close>
              <button
                type="submit"
                disabled={saving || !name.trim()}
                className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {saving && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                )}
                {t(
                  workspace ? 'common.save' : 'aiChat.workspaceControls.create',
                )}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
