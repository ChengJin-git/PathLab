import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, ClipboardList, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import {
  listAnnotationAudit,
  exportAnnotationAuditUrl,
  type AnnotationAuditEntry,
} from '../../api/annotation'
import { getAuthToken } from '../../api/client'

const PAGE_LIMIT = 50

const EVENT_TYPE_OPTIONS = [
  'shared_write',
  'collaborator_add',
  'collaborator_remove',
  'bulk_delete',
] as const

interface Query {
  page: number
  datasetFilter: string
  eventTypeFilter: string
}

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatMetadata(meta: Record<string, unknown>): string {
  return Object.entries(meta)
    .filter(([k]) => k !== 'target_user_id')
    .map(([k, v]) => `${k === 'target_user_display' ? 'user' : k}: ${v}`)
    .join(', ')
}

export function AnnotationAuditCard() {
  const { t } = useTranslation()

  const [query, setQuery] = useState<Query>({ page: 1, datasetFilter: '', eventTypeFilter: '' })
  const [entries, setEntries] = useState<AnnotationAuditEntry[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_LIMIT))

  useEffect(() => {
    let cancelled = false
    const doLoad = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await listAnnotationAudit({
          dataset_id: query.datasetFilter || undefined,
          event_type: query.eventTypeFilter || undefined,
          limit: PAGE_LIMIT,
          offset: (query.page - 1) * PAGE_LIMIT,
        })
        if (!cancelled) {
          setEntries(res.entries)
          setTotalCount(res.count)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    doLoad()
    return () => { cancelled = true }
  }, [query])

  const handleExportCsv = async () => {
    setExporting(true)
    try {
      const url = exportAnnotationAuditUrl({
        dataset_id: query.datasetFilter || undefined,
        event_type: query.eventTypeFilter || undefined,
      })
      const token = getAuthToken()
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      if (!res.ok) return
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'annotation_audit.csv'
      a.click()
      URL.revokeObjectURL(a.href)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="mt-6 bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-5">
        <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <ClipboardList className="w-5 h-5 text-gray-700 flex-shrink-0" />
          {t('settings.usersTab.audit.title')}
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={handleExportCsv}
          disabled={exporting || loading}
          className="gap-1.5 bg-white border-gray-200 text-gray-700 hover:bg-gray-50"
        >
          <Download className="w-3.5 h-3.5" />
          <span className="text-xs font-medium">{t('settings.usersTab.audit.exportCsv')}</span>
        </Button>
      </div>

      <div className="mb-5 p-4 bg-gray-50/80 border border-gray-100 rounded-xl flex flex-col sm:flex-row gap-4">
        <div className="flex-1 space-y-1.5">
          <Label className="text-xs font-medium text-gray-500 uppercase tracking-wider ml-0.5">
            {t('settings.usersTab.audit.filterDataset')}
          </Label>
          <Input
            value={query.datasetFilter}
            onChange={(e) => setQuery(q => ({ ...q, page: 1, datasetFilter: e.target.value }))}
            placeholder={t('settings.usersTab.audit.filterDataset')}
            className="h-9 text-sm"
          />
        </div>
        <div className="w-full sm:w-52 space-y-1.5">
          <Label className="text-xs font-medium text-gray-500 uppercase tracking-wider ml-0.5">
            {t('settings.usersTab.audit.filterEventType')}
          </Label>
          <Select
            value={query.eventTypeFilter}
            onChange={(val) => setQuery(q => ({ ...q, page: 1, eventTypeFilter: val }))}
            options={[
              { value: '', label: t('settings.usersTab.audit.allEvents') },
              ...EVENT_TYPE_OPTIONS.map((et) => ({
                value: et,
                label: t(`settings.usersTab.audit.event_${et}`),
              })),
            ]}
          />
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {loading && entries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-gray-500">
          <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary-600 mb-3" />
          <p className="text-sm">{t('settings.usersTab.audit.loading')}</p>
        </div>
      ) : entries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-gray-400 bg-gray-50/30 rounded-lg border border-dashed border-gray-200">
          <ClipboardList className="w-6 h-6 text-gray-300 mb-2" />
          <p className="text-sm font-medium text-gray-500">{t('settings.usersTab.audit.noEntries')}</p>
        </div>
      ) : (
        <>
          <div className="overflow-hidden rounded-lg border border-gray-200 shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50/80">
                  <tr className="border-b border-gray-200">
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                      {t('settings.usersTab.audit.colTime')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                      {t('settings.usersTab.audit.colUser')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                      {t('settings.usersTab.audit.colDataset')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                      {t('settings.usersTab.audit.colEvent')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                      {t('settings.usersTab.audit.colDetail')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {entries.map((entry) => (
                    <tr key={entry.id} className="hover:bg-gray-50/80 transition-colors">
                      <td className="px-4 py-3 text-xs text-gray-500 font-mono whitespace-nowrap align-top pt-3.5">
                        {formatDateTime(entry.created_at)}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-700 font-medium align-top pt-3.5 truncate max-w-[140px]" title={entry.user_id ?? undefined}>
                        {entry.user_display ?? entry.user_id ?? <span className="text-gray-400">—</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-700 align-top pt-3.5 truncate max-w-[160px]" title={entry.dataset_id}>
                        {entry.dataset_name ?? entry.dataset_id}
                      </td>
                      <td className="px-4 py-3 align-top pt-3.5">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">
                          {t(`settings.usersTab.audit.event_${entry.event_type}`)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500 font-mono align-top pt-3.5 max-w-[240px] truncate" title={formatMetadata(entry.event_metadata)}>
                        {formatMetadata(entry.event_metadata) || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="mt-3 flex items-center justify-between gap-2 text-xs text-gray-500">
            <span>
              {t('settings.usersTab.pageOf', { current: query.page, total: totalPages })}
              {' · '}
              {t('settings.usersTab.totalCount', { count: totalCount })}
            </span>
            <div className="flex items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setQuery(q => ({ ...q, page: Math.max(1, q.page - 1) }))}
                disabled={query.page === 1 || loading}
                className="h-7 w-7 p-0"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setQuery(q => ({ ...q, page: Math.min(totalPages, q.page + 1) }))}
                disabled={query.page >= totalPages || loading}
                className="h-7 w-7 p-0"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
