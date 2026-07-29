import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Loader2, Table2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getPaperFileText } from '../../api/papers'
import { Card, CardContent } from '../ui/card'
import { Badge } from '../ui/badge'

interface TablesTabProps {
  paperId: string
}

interface TableSpec {
  path: string
  labelKey: string
}

interface TableResult extends TableSpec {
  text: string | null
  error: string | null
}

interface ParsedLatexTable {
  headers: string[]
  rows: string[][]
}

const TABLES: TableSpec[] = [
  { path: 'tables/table_1_dataset.tex', labelKey: 'dataset' },
  { path: 'tables/table_2_main_results.tex', labelKey: 'mainResults' },
  { path: 'tables/table_3_per_class.tex', labelKey: 'perClassSplit' },
  { path: 'tables/table_4_ablation.tex', labelKey: 'ablation' },
  { path: 'tables/table_5_external_validation.tex', labelKey: 'externalValidation' },
]

function splitLatexCells(row: string): string[] {
  const cells: string[] = []
  let current = ''
  let escaped = false

  for (const char of row) {
    if (char === '\\' && !escaped) {
      escaped = true
      current += char
      continue
    }
    if (char === '&' && !escaped) {
      cells.push(current)
      current = ''
    } else {
      current += char
    }
    escaped = false
  }

  cells.push(current)
  return cells
}

function unwrapLatexCommands(value: string): string {
  let next = value
  let previous = ''

  while (next !== previous) {
    previous = next
    next = next.replace(/\\(?:textbf|emph|textit|texttt|mathrm|mathbf)\{([^{}]*)\}/g, '$1')
  }

  return next
}

function cleanLatexCell(value: string): string {
  return unwrapLatexCommands(value)
    .replace(/\\(?:cite|ref|label)\{[^{}]*\}/g, '')
    .replace(/\\textsubscript\{([^{}]*)\}/g, '_$1')
    .replace(/\\textsuperscript\{([^{}]*)\}/g, '^$1')
    .replace(/\\_/g, '_')
    .replace(/\\%/g, '%')
    .replace(/\\&/g, '&')
    .replace(/\\#/g, '#')
    .replace(/\\\$/g, '$')
    .replace(/\\pm/g, '+/-')
    .replace(/\\times/g, 'x')
    .replace(/\\,/g, ' ')
    .replace(/[{}$]/g, '')
    .replace(/~/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function parseLatexTable(text: string): ParsedLatexTable | null {
  const bodyMatch = text.match(/\\begin\{tabular\}\{[^}]*\}([\s\S]*?)\\end\{tabular\}/)
  const body = bodyMatch?.[1] ?? text
  const rows = body
    .replace(/%.*$/gm, '')
    .split(/\\\\(?:\s*\[[^\]]*\])?\s*/)
    .map((row) => row
      .replace(/\\(?:toprule|midrule|bottomrule|hline|cline\{[^{}]*\})/g, '')
      .replace(/\\begin\{tabular\}\{[^}]*\}/g, '')
      .replace(/\\end\{tabular\}/g, '')
      .trim())
    .filter((row) => row && row.includes('&'))
    .map((row) => splitLatexCells(row).map(cleanLatexCell))
    .filter((row) => row.some(Boolean))

  if (!rows.length) return null

  const columnCount = Math.max(...rows.map((row) => row.length))
  const normalizedRows = rows.map((row) => Array.from({ length: columnCount }, (_, index) => row[index] ?? ''))
  const headers = normalizedRows[0]
  const dataRows = normalizedRows.slice(1)

  if (!headers.some(Boolean) || !dataRows.length) return null
  return { headers, rows: dataRows }
}

async function loadTables(paperId: string): Promise<TableResult[]> {
  return Promise.all(
    TABLES.map(async (table) => {
      try {
        const text = await getPaperFileText(paperId, table.path)
        return { ...table, text, error: null }
      } catch (error) {
        if (error instanceof ApiError && error.isNotFound()) {
          return { ...table, text: null, error: null }
        }
        return { ...table, text: null, error: error instanceof Error ? error.message : String(error) }
      }
    })
  )
}

export function TablesTab({ paperId }: TablesTabProps) {
  const { t } = useTranslation()
  const tablesQuery = useQuery({
    queryKey: ['paper-tables', paperId],
    queryFn: () => loadTables(paperId),
    retry: false,
  })

  if (tablesQuery.isLoading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.tables.loading')}</div>
  }

  const tables = tablesQuery.data ?? []
  const hasAnyTable = tables.some((table) => table.text)

  if (!hasAnyTable) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <Table2 className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.tables.emptyTitle')}</div>
          <p className="mt-1 text-sm text-slate-500">{t('paperAgent.tables.emptyDescription')}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">{t('paperAgent.tables.title')}</h2>
        <p className="text-sm text-slate-500">{t('paperAgent.tables.description')}</p>
      </div>
      <div className="space-y-4">
        {tables.map((table) => {
          const parsedTable = table.text ? parseLatexTable(table.text) : null

          return (
            <section key={table.path} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
                <div>
                  <div className="font-semibold text-slate-950">{t(`paperAgent.tables.labels.${table.labelKey}`)}</div>
                  <div className="text-xs text-slate-500">{table.path}</div>
                </div>
                {table.error ? <Badge variant="destructive">{t('paperAgent.common.error')}</Badge> : table.text ? <Badge variant="secondary">{t('paperAgent.common.ready')}</Badge> : <Badge variant="outline">{t('paperAgent.common.missing')}</Badge>}
              </div>
              {parsedTable ? (
                <div>
                  <div className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500">
                    {t('paperAgent.tables.tableSummary', { rows: parsedTable.rows.length, columns: parsedTable.headers.length })}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
                      <thead>
                        <tr>
                          {parsedTable.headers.map((header, index) => (
                            <th key={`${table.path}-header-${index}`} className="border-b border-slate-200 bg-white px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-slate-500">
                              {header || t('paperAgent.tables.columnFallback', { index: index + 1 })}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {parsedTable.rows.map((row, rowIndex) => (
                          <tr key={`${table.path}-row-${rowIndex}`} className="odd:bg-white even:bg-slate-50/70">
                            {row.map((cell, cellIndex) => (
                              <td key={`${table.path}-row-${rowIndex}-cell-${cellIndex}`} className="border-b border-slate-100 px-4 py-3 align-top text-slate-700">
                                {cell || <span className="text-slate-300">-</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : table.text ? (
                <div className="space-y-3 p-4">
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    {t('paperAgent.tables.parseFallback')}
                  </div>
                  <pre className="max-h-80 overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-100"><code>{table.text}</code></pre>
                </div>
              ) : (
                <div className="p-4 text-sm text-slate-500">{table.error || t('paperAgent.tables.notGenerated')}</div>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
