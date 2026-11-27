import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import * as Popover from '@radix-ui/react-popover'
import * as Switch from '@radix-ui/react-switch'
import {
  ArrowLeft,
  Check,
  ChevronDown,
  Eye,
  Folder,
  Loader2,
  Plus,
  ScanLine,
  Search,
  Settings2,
  ShieldCheck,
} from 'lucide-react'
import {
  getWorkspaceCapabilities,
  listWorkspaces,
  type Workspace,
  type WorkspaceCapabilities,
} from '../../api/workspaces'
import {
  getWorkspaceSelection,
  type WorkspaceSelection,
} from '../../lib/workspaceSelection'
import { startScanDirectoryTask } from '../../api/storage'
import { invalidateWSIListCache } from '../../api/wsi'
import { invalidateTrainingTasksCache } from '../../api/training'
import { WorkspaceEditor } from './WorkspaceEditor'

interface Props {
  userId: string
  value: WorkspaceSelection
  disabled: boolean
  onChange: (value: WorkspaceSelection, newConversation?: boolean) => void
}

const triggerClass =
  'inline-flex h-9 min-w-0 cursor-pointer items-center gap-1.5 rounded-lg px-2 text-xs text-gray-500 transition-colors hover:bg-gray-100/80 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/30 disabled:cursor-not-allowed disabled:opacity-50 data-[state=open]:bg-gray-100 data-[state=open]:text-gray-900'
const panelClass =
  'z-[60] w-72 max-w-[calc(100vw-24px)] overflow-hidden rounded-2xl border border-gray-200/80 bg-white p-1.5 text-sm text-gray-700 shadow-[0_8px_30px_rgba(0,0,0,0.12)] outline-none'
const rowClass =
  'flex min-h-10 w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50'

function selectionFor(workspace?: Workspace): WorkspaceSelection {
  return {
    workspaceId: workspace?.workspace_id ?? null,
    executionMode: workspace?.execution_mode ?? 'standard',
    expertId: null,
    enabledSkills: workspace?.enabled_skills ?? null,
    enabledConnectors: workspace?.enabled_connectors ?? null,
  }
}

export function WorkspaceControls({
  userId,
  value,
  disabled,
  onChange,
}: Props) {
  const { t } = useTranslation()
  const location = useLocation()
  const [items, setItems] = useState<Workspace[]>([])
  const [capabilities, setCapabilities] =
    useState<WorkspaceCapabilities | null>(null)
  const [menu, setMenu] = useState<'workspace' | 'permission' | null>(null)
  const [query, setQuery] = useState('')
  const [showScanRoots, setShowScanRoots] = useState(false)
  const [editing, setEditing] = useState<Workspace | 'new' | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [scanState, setScanState] = useState<'idle' | 'running' | 'queued'>(
    'idle',
  )
  const searchRef = useRef<HTMLInputElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const currentRef = useRef({ onChange, pathname: location.pathname })
  currentRef.current = { onChange, pathname: location.pathname }
  const active = items.find((item) => item.workspace_id === value.workspaceId)
  const filtered = items.filter((item) =>
    item.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  )
  const readOnly =
    value.executionMode === 'read_only' ||
    active?.execution_mode === 'read_only'
  const label =
    active?.name ??
    t(
      value.workspaceId
        ? 'aiChat.workspaceControls.currentWorkspace'
        : 'aiChat.workspaceControls.allAreas',
    )

  useEffect(() => {
    let live = true
    setLoading(true)
    setError('')
    Promise.all([listWorkspaces(), getWorkspaceCapabilities()])
      .then(([workspaces, catalog]) => {
        if (!live) return
        setItems(workspaces.items)
        setCapabilities(catalog)
        const stored = localStorage.getItem(`pathlab:workspace:${userId}`)
        if (
          !getWorkspaceSelection().workspaceId &&
          !currentRef.current.pathname.match(/dashboard\/.+/)
        ) {
          const workspace = workspaces.items.find(
            (item) => item.workspace_id === stored,
          )
          if (workspace) currentRef.current.onChange(selectionFor(workspace))
        }
      })
      .catch((err) => live && setError(err.message))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [userId])

  useEffect(() => {
    if (disabled) setMenu(null)
  }, [disabled])

  const choose = (workspace?: Workspace) => {
    setMenu(null)
    if ((workspace?.workspace_id ?? null) === value.workspaceId) return
    invalidateWSIListCache()
    invalidateTrainingTasksCache()
    localStorage.setItem(
      `pathlab:workspace:${userId}`,
      workspace?.workspace_id ?? '',
    )
    setScanState('idle')
    onChange(selectionFor(workspace), true)
  }

  const openEditor = (workspace?: Workspace) => {
    setMenu(null)
    setEditing(workspace ?? 'new')
  }

  const handleSaved = (workspace: Workspace) => {
    setItems((prev) => [
      ...prev.filter((item) => item.workspace_id !== workspace.workspace_id),
      workspace,
    ])
    invalidateWSIListCache()
    invalidateTrainingTasksCache()
    localStorage.setItem(`pathlab:workspace:${userId}`, workspace.workspace_id)
    onChange(selectionFor(workspace), true)
    setEditing(null)
  }

  const scan = async (root: string) => {
    setScanState('running')
    setError('')
    try {
      await startScanDirectoryTask(root)
      setScanState('queued')
    } catch (err) {
      setError((err as Error).message)
      setScanState('idle')
    }
  }

  return (
    <div
      className="flex flex-wrap items-center gap-x-1 gap-y-1 px-2 py-1"
      data-testid="workspace-controls"
    >
      <Popover.Root
        open={menu === 'workspace' && !disabled}
        onOpenChange={(open) => {
          setMenu(open ? 'workspace' : null)
          if (open) {
            setQuery('')
            setShowScanRoots(false)
          }
        }}
      >
        <Popover.Trigger asChild>
          <button
            ref={triggerRef}
            type="button"
            disabled={disabled}
            aria-label={t('aiChat.selectWorkspace')}
            title={label}
            className={triggerClass}
          >
            <Folder className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="max-w-40 truncate sm:max-w-56">{label}</span>
            <ChevronDown
              className={`h-3 w-3 shrink-0 transition-transform ${menu === 'workspace' ? 'rotate-180' : ''}`}
              aria-hidden
            />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            side="top"
            align="start"
            sideOffset={6}
            collisionPadding={12}
            className={panelClass}
            aria-label={t('aiChat.selectWorkspace')}
            onOpenAutoFocus={(event) => {
              event.preventDefault()
              searchRef.current?.focus()
            }}
            onCloseAutoFocus={(event) => {
              if (editing) event.preventDefault()
            }}
          >
            {showScanRoots ? (
              <>
                <button
                  type="button"
                  onClick={() => setShowScanRoots(false)}
                  className={rowClass}
                >
                  <ArrowLeft className="h-4 w-4" aria-hidden />
                  {t('aiChat.workspaceControls.back')}
                </button>
                <div className="my-1 border-t border-gray-100" />
                {active?.root_paths.map((root) => (
                  <button
                    key={root}
                    type="button"
                    disabled={readOnly || scanState === 'running'}
                    className={rowClass}
                    title={root}
                    onClick={() => void scan(root)}
                  >
                    <ScanLine className="h-4 w-4 shrink-0" aria-hidden />
                    <span className="truncate">{root}</span>
                  </button>
                ))}
                {scanState !== 'idle' && (
                  <p
                    role="status"
                    className="px-2.5 py-2 text-xs text-gray-500"
                  >
                    {t(
                      `aiChat.workspaceControls.scan${scanState === 'running' ? 'Running' : 'Queued'}`,
                    )}
                  </p>
                )}
              </>
            ) : (
              <>
                <div className="m-1 flex items-center gap-2 rounded-lg bg-gray-50 px-2.5 py-2 focus-within:ring-2 focus-within:ring-primary-500/20">
                  <Search
                    className="h-4 w-4 shrink-0 text-gray-400"
                    aria-hidden
                  />
                  <input
                    ref={searchRef}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    aria-label={t('aiChat.searchWorkspace')}
                    placeholder={t('aiChat.searchWorkspace')}
                    className="w-full min-w-0 bg-transparent text-sm outline-none placeholder:text-gray-400"
                  />
                </div>
                <div
                  className="max-h-60 overflow-y-auto overscroll-contain py-1"
                  aria-busy={loading}
                >
                  <button
                    type="button"
                    className={rowClass}
                    onClick={() => choose()}
                    aria-pressed={!value.workspaceId}
                  >
                    <Folder
                      className="h-4 w-4 shrink-0 text-gray-500"
                      aria-hidden
                    />
                    <span className="flex-1">
                      {t('aiChat.workspaceControls.allAreas')}
                    </span>
                    {!value.workspaceId && (
                      <Check className="h-4 w-4 shrink-0" aria-hidden />
                    )}
                  </button>
                  {filtered.map((item) => (
                    <button
                      key={item.workspace_id}
                      type="button"
                      className={rowClass}
                      onClick={() => choose(item)}
                      aria-pressed={value.workspaceId === item.workspace_id}
                      title={item.name}
                    >
                      <Folder
                        className="h-4 w-4 shrink-0 text-gray-500"
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {item.name}
                      </span>
                      {value.workspaceId === item.workspace_id && (
                        <Check className="h-4 w-4 shrink-0" aria-hidden />
                      )}
                    </button>
                  ))}
                  {loading && (
                    <div
                      role="status"
                      className="flex items-center justify-center gap-2 py-3 text-xs text-gray-500"
                    >
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin"
                        aria-hidden
                      />
                      {t('common.loading')}
                    </div>
                  )}
                  {!loading && !filtered.length && query && (
                    <p className="px-3 py-3 text-center text-xs text-gray-500">
                      {t('aiChat.noMatchingWorkspace')}
                    </p>
                  )}
                </div>
                <div className="my-1 border-t border-gray-100" />
                <button
                  type="button"
                  disabled={!capabilities}
                  className={rowClass}
                  onClick={() => openEditor()}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  {t('aiChat.newWorkspace')}
                </button>
                {active && (
                  <button
                    type="button"
                    disabled={!capabilities}
                    className={rowClass}
                    onClick={() => openEditor(active)}
                  >
                    <Settings2 className="h-4 w-4" aria-hidden />
                    {t('aiChat.workspaceControls.manage')}
                  </button>
                )}
                {active?.root_paths.length && capabilities?.can_scan_server ? (
                  <button
                    type="button"
                    disabled={readOnly}
                    className={rowClass}
                    onClick={() => setShowScanRoots(true)}
                  >
                    <ScanLine className="h-4 w-4" aria-hidden />
                    {t('aiChat.workspaceControls.scanDirectories')}
                  </button>
                ) : null}
              </>
            )}
            {error && (
              <p role="alert" className="px-2.5 py-2 text-xs text-red-600">
                {error}
              </p>
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>

      <Popover.Root
        open={menu === 'permission' && !disabled}
        onOpenChange={(open) => setMenu(open ? 'permission' : null)}
      >
        <Popover.Trigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label={t('aiChat.workspaceControls.permissions')}
            className={triggerClass}
          >
            {readOnly ? (
              <Eye className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            )}
            <span>
              {t(
                readOnly
                  ? 'aiChat.workspaceControls.readOnly'
                  : 'aiChat.defaultPermission',
              )}
            </span>
            <ChevronDown
              className={`h-3 w-3 transition-transform ${menu === 'permission' ? 'rotate-180' : ''}`}
              aria-hidden
            />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            side="top"
            align="start"
            sideOffset={6}
            collisionPadding={12}
            className={`${panelClass} w-64 p-3.5`}
            aria-label={t('aiChat.workspaceControls.permissions')}
          >
            <p className="text-xs leading-5 text-gray-500">
              {t(
                active?.execution_mode === 'read_only'
                  ? 'aiChat.workspaceControls.lockedHint'
                  : readOnly
                    ? 'aiChat.workspaceControls.readOnlyHint'
                    : 'aiChat.defaultPermissionHint',
              )}
            </p>
            <div className="mt-3 flex items-center justify-between gap-4 border-t border-gray-100 pt-3">
              <span className="text-sm text-gray-800">
                {t('aiChat.workspaceControls.readOnly')}
              </span>
              <Switch.Root
                checked={readOnly}
                disabled={active?.execution_mode === 'read_only'}
                aria-label={t('aiChat.workspaceControls.readOnly')}
                onCheckedChange={(checked) =>
                  onChange({
                    ...value,
                    executionMode: checked ? 'read_only' : 'standard',
                  })
                }
                className="inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full bg-gray-200 p-0.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/30 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-gray-900"
              >
                <Switch.Thumb className="h-4 w-4 rounded-full bg-white shadow-sm transition-transform data-[state=checked]:translate-x-4 motion-reduce:transition-none" />
              </Switch.Root>
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>

      {error && !menu && (
        <p role="alert" className="w-full px-2 text-xs text-red-600">
          {error}
        </p>
      )}
      {editing && capabilities && (
        <WorkspaceEditor
          key={editing === 'new' ? 'new' : editing.workspace_id}
          workspace={editing === 'new' ? undefined : editing}
          capabilities={capabilities}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
          onCloseAutoFocus={() => triggerRef.current?.focus()}
          onArchived={(id) => {
            setItems((prev) => prev.filter((item) => item.workspace_id !== id))
            choose()
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}
