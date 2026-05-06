import { useQuery } from '@tanstack/react-query'
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
  label: string
}

interface TableResult extends TableSpec {
  text: string | null
  error: string | null
}

const TABLES: TableSpec[] = [
  { path: 'tables/table_1_dataset.tex', label: 'Dataset' },
  { path: 'tables/table_2_main_results.tex', label: 'Main results' },
  { path: 'tables/table_3_per_class.tex', label: 'Per-class / split' },
  { path: 'tables/table_4_ablation.tex', label: 'Ablation' },
  { path: 'tables/table_5_external_validation.tex', label: 'External validation' },
]

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
  const tablesQuery = useQuery({
    queryKey: ['paper-tables', paperId],
    queryFn: () => loadTables(paperId),
    retry: false,
  })

  if (tablesQuery.isLoading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading tables...</div>
  }

  const tables = tablesQuery.data ?? []
  const hasAnyTable = tables.some((table) => table.text)

  if (!hasAnyTable) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <Table2 className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">Locked-block tables not generated yet</div>
          <p className="mt-1 text-sm text-slate-500">The building_evidence stage writes deterministic LaTeX tables.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">Locked tables</h2>
        <p className="text-sm text-slate-500">Read-only LaTeX from the deterministic table artifacts.</p>
      </div>
      <div className="space-y-4">
        {tables.map((table) => (
          <section key={table.path} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
              <div>
                <div className="font-semibold text-slate-950">{table.label}</div>
                <div className="text-xs text-slate-500">{table.path}</div>
              </div>
              {table.error ? <Badge variant="destructive">error</Badge> : table.text ? <Badge variant="secondary">ready</Badge> : <Badge variant="outline">missing</Badge>}
            </div>
            {table.text ? (
              <pre className="max-h-80 overflow-auto bg-slate-950 p-4 text-xs leading-6 text-slate-100"><code>{table.text}</code></pre>
            ) : (
              <div className="p-4 text-sm text-slate-500">{table.error || 'Not generated for this run.'}</div>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
