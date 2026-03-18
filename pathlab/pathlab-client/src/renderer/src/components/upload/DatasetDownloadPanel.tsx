import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Download,
  X,
  FileDown,
  CheckCircle2,
  AlertCircle,
  Loader2,
  File,
  Clock,
  Globe,
  Database,
} from 'lucide-react'
import { Card, CardContent } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Progress } from '../ui/progress'
import {
  startDatasetDownload,
  streamDownloadProgress,
  cancelDownload,
  listDownloads,
  type DownloadSourceType,
  type DownloadTaskInfo,
} from '../../api/dataset-download'

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

function formatSpeed(bytesPerSec: number): string {
  return `${formatBytes(bytesPerSec)}/s`
}

const SOURCE_TABS: { key: DownloadSourceType; label: string; icon: typeof Database; placeholder: string; hint: string }[] = [
  { key: 'huggingface', label: 'HuggingFace', icon: Database, placeholder: 'username/dataset-name', hint: 'e.g. hf-internal-testing/fixtures_image_utils' },
  { key: 'kaggle', label: 'Kaggle', icon: Database, placeholder: 'owner/dataset-name', hint: 'e.g. username/dataset-slug' },
  { key: 'geo', label: 'GEO', icon: Database, placeholder: 'GSE12345', hint: 'NCBI GEO accession (GSExxxxx, GPLxxxxx, GSMxxxxx)' },
  { key: 'zenodo', label: 'Zenodo', icon: Database, placeholder: '12345', hint: 'Zenodo record ID or URL (e.g. 12345 or https://zenodo.org/records/12345)' },
  { key: 'url', label: 'URL', icon: Globe, placeholder: 'https://example.com/data.zip', hint: 'Direct download URL (supports zip, tar.gz auto-extract)' },
]

interface ActiveDownload {
  taskId: string
  info: DownloadTaskInfo | null
  cleanup?: () => void
}

export function DatasetDownloadPanel() {
  const { t } = useTranslation()
  const [sourceType, setSourceType] = useState<DownloadSourceType>('huggingface')
  const [identifier, setIdentifier] = useState('')
  const [filePatterns, setFilePatterns] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [activeDownloads, setActiveDownloads] = useState<Map<string, ActiveDownload>>(new Map)
  const [history, setHistory] = useState<DownloadTaskInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const cleanupRefs = useRef<Map<string, () => void>>(new Map())

  // Connect SSE for a single active task
  const connectSSE = useCallback((taskId: string) => {
    // Don't double-connect
    if (cleanupRefs.current.has(taskId)) return

    const cleanup = streamDownloadProgress(
      taskId,
      (data) => {
        setActiveDownloads(prev => {
          const next = new Map(prev)
          next.set(taskId, { taskId, info: data })
          return next
        })
      },
      (err) => {
        console.error('Download SSE error:', err)
      },
      () => {
        cleanupRefs.current.delete(taskId)
        // Reload all tasks when one finishes
        loadAllTasks()
      },
    )
    cleanupRefs.current.set(taskId, cleanup)
  }, [])

  // Load all tasks from backend; reconnect SSE for active ones
  const loadAllTasks = useCallback(async () => {
    try {
      const result = await listDownloads()
      const active = new Map<string, ActiveDownload>()
      const done: DownloadTaskInfo[] = []

      for (const task of result.items) {
        if (task.status === 'pending' || task.status === 'downloading') {
          active.set(task.task_id, { taskId: task.task_id, info: task })
          connectSSE(task.task_id)
        } else {
          done.push(task)
        }
      }

      setActiveDownloads(prev => {
        // Merge: keep any entries from prev that are still active (SSE may have fresher data)
        const merged = new Map(active)
        prev.forEach((v, k) => {
          if (merged.has(k) && v.info) {
            merged.set(k, v) // keep SSE-updated version
          }
        })
        return merged
      })
      setHistory(done)
    } catch {
      // ignore
    }
  }, [connectSSE])

  // On mount: load tasks & reconnect SSE; on unmount: close SSE
  useEffect(() => {
    loadAllTasks()
    return () => {
      cleanupRefs.current.forEach(cleanup => cleanup())
      cleanupRefs.current.clear()
    }
  }, [loadAllTasks])

  const handleStartDownload = async () => {
    if (!identifier.trim()) return

    setIsSubmitting(true)
    setError(null)

    try {
      const patterns = filePatterns.trim()
        ? filePatterns.split(',').map(p => p.trim()).filter(Boolean)
        : undefined

      const result = await startDatasetDownload({
        source_type: sourceType,
        identifier: identifier.trim(),
        file_patterns: patterns,
      })

      const taskId = result.task_id

      // Add to active downloads and connect SSE
      setActiveDownloads(prev => new Map(prev).set(taskId, { taskId, info: null }))
      connectSSE(taskId)

      setIdentifier('')
      setFilePatterns('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start download')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = async (taskId: string) => {
    try {
      await cancelDownload(taskId)
      const cleanup = cleanupRefs.current.get(taskId)
      if (cleanup) {
        cleanup()
        cleanupRefs.current.delete(taskId)
      }
      setActiveDownloads(prev => {
        const next = new Map(prev)
        const existing = next.get(taskId)
        if (existing && existing.info) {
          next.set(taskId, { ...existing, info: { ...existing.info, status: 'cancelled' } })
        }
        return next
      })
      loadAllTasks()
    } catch {
      // ignore
    }
  }

  const currentSource = SOURCE_TABS.find(s => s.key === sourceType)!

  return (
    <div className="space-y-6">
      {/* Source selection + input */}
      <Card className="border border-slate-200 shadow-sm">
        <CardContent className="p-5 space-y-4">
          {/* Source tabs */}
          <div className="flex gap-1 p-1 bg-slate-100 rounded-lg">
            {SOURCE_TABS.map(src => (
              <button
                key={src.key}
                onClick={() => setSourceType(src.key)}
                className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  sourceType === src.key
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`}
              >
                <src.icon className="w-3.5 h-3.5" />
                {src.label}
              </button>
            ))}
          </div>

          {/* Input form */}
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-sm font-medium text-slate-700">
                {sourceType === 'url' ? 'URL' : 'Dataset ID'}
              </Label>
              <Input
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                placeholder={currentSource.placeholder}
                className="h-10"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !isSubmitting) handleStartDownload()
                }}
              />
              <p className="text-xs text-slate-500">{currentSource.hint}</p>
            </div>

            {/* File patterns (for HuggingFace / Zenodo) */}
            {(sourceType === 'huggingface' || sourceType === 'zenodo') && (
              <div className="space-y-1.5">
                <Label className="text-sm font-medium text-slate-700">
                  File Patterns <span className="text-slate-400 font-normal">(optional)</span>
                </Label>
                <Input
                  value={filePatterns}
                  onChange={(e) => setFilePatterns(e.target.value)}
                  placeholder="*.parquet, *.csv, data/**"
                  className="h-9 text-sm"
                />
                <p className="text-xs text-slate-500">
                  Comma-separated glob patterns to filter files
                </p>
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                {error}
              </div>
            )}

            <Button
              onClick={handleStartDownload}
              disabled={isSubmitting || !identifier.trim()}
              className="w-full h-10"
            >
              {isSubmitting ? (
                <Loader2 className="w-4 h-4 animate-spin mr-2" />
              ) : (
                <Download className="w-4 h-4 mr-2" />
              )}
              {isSubmitting ? 'Starting...' : 'Start Download'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Active downloads */}
      {activeDownloads.size > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Active Downloads
          </h3>
          {Array.from(activeDownloads.values()).map(dl => (
            <DownloadProgressCard
              key={dl.taskId}
              taskId={dl.taskId}
              info={dl.info}
              onCancel={() => handleCancel(dl.taskId)}
            />
          ))}
        </div>
      )}

      {/* Download history */}
      {history.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Download History
          </h3>
          {history.map(task => (
            <DownloadHistoryCard key={task.task_id} task={task} />
          ))}
        </div>
      )}
    </div>
  )
}

function DownloadProgressCard({
  taskId,
  info,
  onCancel,
}: {
  taskId: string
  info: DownloadTaskInfo | null
  onCancel: () => void
}) {
  if (!info) {
    return (
      <Card className="border border-blue-200 bg-blue-50/50">
        <CardContent className="p-4 flex items-center gap-3">
          <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
          <span className="text-sm text-slate-600">Initializing download...</span>
        </CardContent>
      </Card>
    )
  }

  const progress = info.progress
  const isIndeterminate = info.status === 'downloading' && progress.total_bytes === 0 && progress.downloaded_bytes === 0
  const pct = progress.total_bytes > 0
    ? Math.round((progress.downloaded_bytes / progress.total_bytes) * 100)
    : 0

  const isTerminal = ['completed', 'failed', 'cancelled'].includes(info.status)

  return (
    <Card className={`border ${
      info.status === 'completed' ? 'border-emerald-200 bg-emerald-50/50' :
      info.status === 'failed' ? 'border-red-200 bg-red-50/50' :
      info.status === 'cancelled' ? 'border-slate-200 bg-slate-50' :
      'border-blue-200 bg-blue-50/50'
    }`}>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <StatusIcon status={info.status} />
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-900 truncate">
                {info.identifier}
              </p>
              <p className="text-xs text-slate-500">
                {info.source_type.toUpperCase()} · {info.status}
              </p>
            </div>
          </div>
          {!isTerminal && (
            <Button variant="ghost" size="sm" onClick={onCancel} className="text-slate-500 hover:text-red-600">
              <X className="w-4 h-4" />
            </Button>
          )}
        </div>

        {info.status === 'downloading' && (
          <>
            {isIndeterminate ? (
              <div className="h-2 w-full bg-blue-100 rounded-full overflow-hidden">
                <div className="h-full w-1/3 bg-blue-500 rounded-full animate-[indeterminate_1.5s_ease-in-out_infinite]"
                  style={{ animation: 'indeterminate 1.5s ease-in-out infinite' }}
                />
                <style>{`@keyframes indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }`}</style>
              </div>
            ) : (
              <Progress value={pct} className="h-2" />
            )}
            <div className="flex justify-between text-xs text-slate-500">
              <span>
                {progress.current_file && (
                  <span className="text-slate-600">{progress.current_file}</span>
                )}
              </span>
              <span>
                {isIndeterminate
                  ? 'Downloading...'
                  : <>
                      {formatBytes(progress.downloaded_bytes)}
                      {progress.total_bytes > 0 && ` / ${formatBytes(progress.total_bytes)}`}
                      {progress.speed > 0 && ` · ${formatSpeed(progress.speed)}`}
                    </>
                }
              </span>
            </div>
          </>
        )}

        {info.status === 'failed' && info.error && (
          <p className="text-xs text-red-600">{info.error}</p>
        )}

        {info.status === 'completed' && info.files.length > 0 && (
          <div className="text-xs text-slate-600">
            {info.files.length} files · {formatBytes(info.total_size)}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DownloadHistoryCard({ task }: { task: DownloadTaskInfo }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card className="border border-slate-200">
      <CardContent className="p-3">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between text-left"
        >
          <div className="flex items-center gap-2 min-w-0">
            <StatusIcon status={task.status} />
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-700 truncate">{task.identifier}</p>
              <p className="text-xs text-slate-500">
                {task.source_type.toUpperCase()}
                {task.total_size > 0 && ` · ${formatBytes(task.total_size)}`}
                {task.files.length > 0 && ` · ${task.files.length} files`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {task.status === 'cancelled' && (
              <span className="text-xs font-medium text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">Cancelled</span>
            )}
            {task.status === 'failed' && (
              <span className="text-xs font-medium text-red-500 bg-red-50 px-1.5 py-0.5 rounded">Failed</span>
            )}
            {task.status === 'completed' && (
              <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">Completed</span>
            )}
            <span className="text-xs text-slate-400">
              {task.created_at && new Date(task.created_at).toLocaleDateString()}
            </span>
          </div>
        </button>

        {expanded && task.files.length > 0 && (
          <div className="mt-3 border-t border-slate-100 pt-3 space-y-1 max-h-48 overflow-y-auto">
            {task.files.map((f, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-slate-600">
                <File className="w-3 h-3 flex-shrink-0 text-slate-400" />
                <span className="truncate flex-1">{f.filename}</span>
                <span className="text-slate-400 flex-shrink-0">{formatBytes(f.size)}</span>
              </div>
            ))}
          </div>
        )}

        {task.status === 'failed' && task.error && (
          <p className="mt-2 text-xs text-red-500">{task.error}</p>
        )}
      </CardContent>
    </Card>
  )
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
    case 'failed':
      return <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
    case 'cancelled':
      return <X className="w-4 h-4 text-slate-400 flex-shrink-0" />
    case 'downloading':
      return <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />
    default:
      return <FileDown className="w-4 h-4 text-slate-400 flex-shrink-0" />
  }
}
