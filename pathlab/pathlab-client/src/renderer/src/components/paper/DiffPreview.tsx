import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FileText, Loader2 } from 'lucide-react'
import { getPaperFileText, type DiffSummary } from '../../api/papers'
import { cn } from '../../lib/utils'

interface DiffPreviewProps {
  paperId: string
  beforePath?: string | null
  afterPath?: string | null
  diffSummary?: DiffSummary | null
}

type DiffPart = {
  type: 'same' | 'added' | 'removed'
  text: string
}

function tokenizeForDiff(text: string): string[] {
  return text.match(/\s+|[^\s]+/g) ?? []
}

function compactWordDiff(before: string, after: string): DiffPart[] {
  const beforeTokens = tokenizeForDiff(before)
  const afterTokens = tokenizeForDiff(after)
  let prefix = 0

  while (prefix < beforeTokens.length && prefix < afterTokens.length && beforeTokens[prefix] === afterTokens[prefix]) {
    prefix += 1
  }

  let beforeSuffix = beforeTokens.length - 1
  let afterSuffix = afterTokens.length - 1
  while (beforeSuffix >= prefix && afterSuffix >= prefix && beforeTokens[beforeSuffix] === afterTokens[afterSuffix]) {
    beforeSuffix -= 1
    afterSuffix -= 1
  }

  const parts: DiffPart[] = []
  const prefixText = beforeTokens.slice(0, prefix).join('')
  const removedText = beforeTokens.slice(prefix, beforeSuffix + 1).join('')
  const addedText = afterTokens.slice(prefix, afterSuffix + 1).join('')
  const suffixText = beforeTokens.slice(beforeSuffix + 1).join('')

  if (prefixText) parts.push({ type: 'same', text: prefixText })
  if (removedText) parts.push({ type: 'removed', text: removedText })
  if (addedText) parts.push({ type: 'added', text: addedText })
  if (suffixText) parts.push({ type: 'same', text: suffixText })

  return parts
}

function trimSourcePreview(text: string, truncatedLabel: string, maxChars = 7000): string {
  if (text.length <= maxChars) return text
  return `${text.slice(0, maxChars)}\n\n${truncatedLabel}`
}

function unifiedLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-slate-400'
  if (line.startsWith('+')) return 'bg-emerald-50 text-emerald-800'
  if (line.startsWith('-')) return 'bg-red-50 text-red-800'
  if (line.startsWith('@')) return 'bg-slate-100 text-slate-500'
  return 'text-slate-600'
}

export function DiffPreview({ paperId, beforePath, afterPath, diffSummary }: DiffPreviewProps) {
  const { t } = useTranslation()
  const beforeQuery = useQuery({
    queryKey: ['paper-file-text', paperId, beforePath],
    queryFn: () => getPaperFileText(paperId, beforePath || ''),
    enabled: Boolean(beforePath),
    retry: false,
  })

  const afterQuery = useQuery({
    queryKey: ['paper-file-text', paperId, afterPath],
    queryFn: () => getPaperFileText(paperId, afterPath || ''),
    enabled: Boolean(afterPath),
    retry: false,
  })

  const hasBeforeAfter = Boolean(beforeQuery.data && afterQuery.data)
  const diffParts = useMemo(() => {
    if (!beforeQuery.data || !afterQuery.data) return []
    return compactWordDiff(
      trimSourcePreview(beforeQuery.data, t('paperAgent.diff.truncated')),
      trimSourcePreview(afterQuery.data, t('paperAgent.diff.truncated')),
    )
  }, [afterQuery.data, beforeQuery.data, t])

  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-slate-200 bg-white p-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <FileText className="h-4 w-4 text-sky-500" />
            {t('paperAgent.diff.title')}
          </div>
          {diffSummary ? (
            <div className="flex flex-wrap justify-end gap-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500">
              <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700">+{diffSummary.chars_added}</span>
              <span className="rounded-full bg-red-50 px-2 py-1 text-red-700">-{diffSummary.chars_removed}</span>
              <span className="rounded-full bg-slate-100 px-2 py-1">
                {t('paperAgent.diff.paragraphs', { count: diffSummary.paragraphs_changed?.length ?? 0 })}
              </span>
            </div>
          ) : null}
        </div>

        {beforeQuery.isLoading || afterQuery.isLoading ? (
          <div className="flex items-center gap-2 rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('paperAgent.diff.loading')}
          </div>
        ) : hasBeforeAfter ? (
          <div className="max-h-72 overflow-auto rounded-xl border border-slate-100 bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100">
            {diffParts.map((part, index) => (
              <span
                key={`${part.type}-${index}`}
                className={cn(
                  part.type === 'added' && 'rounded bg-emerald-400/25 text-emerald-100',
                  part.type === 'removed' && 'rounded bg-red-400/25 text-red-100 line-through decoration-red-200/70',
                  part.type === 'same' && 'text-slate-200',
                )}
              >
                {part.text}
              </span>
            ))}
          </div>
        ) : diffSummary?.preview_unified ? (
          <pre className="max-h-72 overflow-auto rounded-xl border border-slate-100 bg-slate-50 p-3 text-xs leading-5">
            {diffSummary.preview_unified.split('\n').map((line, index) => (
              <div key={`${index}-${line.slice(0, 12)}`} className={cn('px-1 font-mono', unifiedLineClass(line))}>
                {line || ' '}
              </div>
            ))}
          </pre>
        ) : (
          <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
            {t('paperAgent.diff.empty')}
          </div>
        )}

        {beforeQuery.error || afterQuery.error ? (
          <div className="mt-2 rounded-xl border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
            {t('paperAgent.diff.snapshotFailed')}
          </div>
        ) : null}
      </div>
    </div>
  )
}
