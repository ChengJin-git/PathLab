import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ArrowLeft, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { WorkspaceTabs, coerceWorkspaceTab, type WorkspaceTabValue } from '../components/paper/WorkspaceTabs'
import { DeleteRunButton } from '../components/paper/DeleteRunButton'
import { getPaperRun, postPaperStageRerun, type PaperRunStage, type PostPaperStageRerunBody } from '../api/papers'
import { paperStageDiagnosticMessage, paperStatusLabel } from '../lib/paperI18n'

const ACTIVE_STATUSES = new Set(['pending', 'running'])
const ACTIVE_RUN_REFETCH_INTERVAL_MS = 500
const OUTLINE_RERUN_STAGES = new Set(['collecting', 'building_evidence', 'outlining'])
const SECTION_OVERWRITE_STAGES = new Set(['collecting', 'building_evidence', 'outlining', 'plotting', 'literature_review', 'section_writing'])
const CITATION_OVERWRITE_STAGES = new Set(['collecting', 'building_evidence', 'outlining', 'plotting', 'literature_review'])

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'secondary'
  if (status === 'failed' || status === 'cancelled') return 'destructive'
  if (status === 'running') return 'default'
  return 'outline'
}

export default function PaperRunDetailPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { paper_id: paperId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [pdfRefreshKey, setPdfRefreshKey] = useState(0)
  const activeTab = coerceWorkspaceTab(searchParams.get('tab'))

  const runQuery = useQuery({
    queryKey: ['paper-run', paperId],
    queryFn: () => getPaperRun(paperId || ''),
    enabled: Boolean(paperId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ACTIVE_STATUSES.has(status) ? ACTIVE_RUN_REFETCH_INTERVAL_MS : false
    },
  })

  const rerunMutation = useMutation({
    mutationFn: ({ stage, body }: { stage: PaperRunStage; body: PostPaperStageRerunBody }) =>
      postPaperStageRerun(paperId || '', stage, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
      await queryClient.invalidateQueries({ queryKey: ['paper-file', paperId] })
    },
  })
  const setActiveTab = (tab: WorkspaceTabValue | string) => {
    const next = new URLSearchParams(searchParams)
    next.set('tab', coerceWorkspaceTab(tab))
    setSearchParams(next)
  }

  const bumpPdfRefreshKey = () => {
    setPdfRefreshKey((key) => key + 1)
  }

  const run = runQuery.data
  const runErrorMessage = paperStageDiagnosticMessage(t, run?.error_message)
  const mutationError = rerunMutation.error
  const rerunningStage = rerunMutation.isPending ? (rerunMutation.variables?.stage ?? null) : null
  const mutationErrorMessage = paperStageDiagnosticMessage(
    t,
    mutationError instanceof Error ? mutationError.message : mutationError ? String(mutationError) : '',
  )
  const hasUserSectionEdits = (run?.stage_log ?? []).some((entry) => entry.stage === 'section_writing' && entry.status === 'user_edited')
  const hasUserCitationEdits = (run?.stage_log ?? []).some((entry) => entry.stage === 'literature_review' && ['user_added', 'user_removed'].includes(entry.status))

  const rerunBodyForStage = (stage: PaperRunStage): PostPaperStageRerunBody | null => {
    const stageValue = String(stage)
    const needsOutlineConfirm = OUTLINE_RERUN_STAGES.has(stageValue)
    const needsSectionConfirm = hasUserSectionEdits && SECTION_OVERWRITE_STAGES.has(stageValue)
    const needsCitationConfirm = hasUserCitationEdits && CITATION_OVERWRITE_STAGES.has(stageValue)
    const prompts = [
      needsOutlineConfirm ? t('paperAgent.rerun.confirmOutline') : '',
      needsSectionConfirm ? t('paperAgent.rerun.confirmSections') : '',
      needsCitationConfirm ? t('paperAgent.rerun.confirmCitations') : '',
      t('paperAgent.rerun.confirmDownstream'),
    ].filter(Boolean)
    if (prompts.length && !window.confirm(prompts.join('\n\n'))) return null
    return {
      continue_downstream: true,
      include_previous_successful_output: true,
      confirm_regenerate_outline: needsOutlineConfirm,
      confirm_overwrite_sections: needsSectionConfirm,
      confirm_overwrite_citations: needsCitationConfirm,
    }
  }

  const handleRerunStage = (stage: PaperRunStage) => {
    if (!paperId || rerunMutation.isPending) return
    const body = rerunBodyForStage(stage)
    if (!body) return
    rerunMutation.mutate({ stage, body })
  }

  return (
    <div className="w-full px-3 py-4 sm:px-4 lg:px-6 sm:py-6">
      <div className="flex w-full flex-col gap-5">
        <PageHeader
          title={run?.title || t('paperAgent.detail.fallbackTitle')}
          className="mb-3 items-start gap-5 pb-5 lg:flex-row"
          contentClassName="max-w-[78rem]"
          titleClassName="max-w-[24ch] text-[2rem] font-semibold leading-[1.08] tracking-[-0.025em] sm:text-[2.45rem] lg:text-[2.75rem] xl:max-w-[30ch]"
          actionsClassName="w-full items-start justify-start gap-2 sm:w-auto sm:justify-end lg:pt-1"
        >
          <div className="flex flex-wrap items-center gap-2 sm:max-w-[18rem] sm:justify-end">
            {run ? <Badge variant={statusBadgeVariant(run.status)} className="h-9 px-3 tracking-[0.18em] shadow-sm shadow-red-100/60">{paperStatusLabel(t, run.status)}</Badge> : null}
            <Button variant="outline" size="sm" onClick={() => navigate('/papers')} className="h-10 gap-2 px-3.5 text-sm shadow-sm">
              <ArrowLeft className="h-4 w-4" />
              {t('paperAgent.common.runs')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => runQuery.refetch()} className="h-10 gap-2 px-3.5 text-sm shadow-sm">
              <RefreshCw className="h-4 w-4" />
              {t('paperAgent.common.refresh')}
            </Button>
            {paperId ? <DeleteRunButton paperId={paperId} onDeleted={() => navigate('/papers')} className="h-10 px-3.5 text-sm shadow-sm" /> : null}
          </div>
        </PageHeader>

        {runQuery.isLoading ? (
          <Card className="rounded-2xl border-slate-200 shadow-sm">
            <CardContent className="flex items-center gap-2 py-10 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.detail.loading')}
            </CardContent>
          </Card>
        ) : runQuery.error ? (
          <Card className="rounded-2xl border-red-200 bg-red-50 shadow-sm">
            <CardContent className="py-6 text-sm text-red-700">
              {runQuery.error instanceof Error ? runQuery.error.message : String(runQuery.error)}
            </CardContent>
          </Card>
        ) : run && paperId ? (
          <div className="flex flex-col gap-4">
            {run.status === 'failed' ? (
              <Card className="overflow-hidden rounded-2xl border-red-100 bg-white shadow-sm ring-1 ring-red-100/70">
                <CardContent className="flex flex-col p-0 sm:flex-row sm:items-stretch sm:justify-between">
                  <div className="flex min-w-0 flex-1 items-start gap-3 px-4 py-4 text-sm">
                    <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-50 text-red-600">
                      <AlertTriangle className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 pt-0.5">
                      <div className="font-semibold text-slate-950">{t('paperAgent.rerun.failedTitle')}</div>
                      <div className="mt-1 max-w-5xl break-words text-sm leading-5 text-red-700">{runErrorMessage || t('paperAgent.rerun.failedDescription')}</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ) : null}
            {mutationError ? (
              <div className="rounded-xl border border-red-100 bg-white px-3 py-2 text-sm text-red-700 shadow-sm">
                {mutationErrorMessage}
              </div>
            ) : null}
            <WorkspaceTabs
              paperId={paperId}
              run={run}
              value={activeTab}
              onValueChange={setActiveTab}
              pdfRefreshKey={pdfRefreshKey}
              onPdfRefreshNeeded={bumpPdfRefreshKey}
              onRerunStage={handleRerunStage}
              rerunningStage={rerunningStage}
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}
