import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, BarChart3, BookOpenText, Braces, CheckCircle2, FileText, Loader2, PencilLine, PlayCircle, Plus, Save, Settings2, Trash2, X } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getPaperFileJson, putPaperOutline, type OutlineDocument, type PaperRunDetail } from '../../api/papers'
import { Card, CardContent } from '../ui/card'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { paperStageLabel } from '../../lib/paperI18n'
import { cn } from '../../lib/utils'
import { labelForSection } from './SectionsTab'

interface OutlineTabProps {
  paperId: string
  run: PaperRunDetail
}

type OutlineModule = 'sections' | 'figures' | 'literature' | 'extensions'
type SectionPlanItem = OutlineDocument['section_plan'][number]
type PlottingPlanItem = OutlineDocument['plotting_plan'][number]
type MicroLitCluster = OutlineDocument['micro_lit_clusters'][number]

const MODULES: { id: OutlineModule; icon: typeof FileText }[] = [
  { id: 'sections', icon: FileText },
  { id: 'figures', icon: BarChart3 },
  { id: 'literature', icon: BookOpenText },
  { id: 'extensions', icon: Settings2 },
]

const POST_OUTLINE_STAGES = new Set([
  'plotting',
  'literature_review',
  'section_writing',
  'validating',
  'refining',
  'rendering',
  'exporting',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validateOutlineDocument(value: unknown): value is OutlineDocument {
  if (!isRecord(value)) return false
  return (
    Array.isArray(value.plotting_plan) &&
    Array.isArray(value.macro_lit_search) &&
    Array.isArray(value.micro_lit_clusters) &&
    Array.isArray(value.section_plan) &&
    isRecord(value.pathlab_extensions)
  )
}

function artifactUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  if (error.isNotFound()) return true
  const detail = error.details || error.message
  return error.status === 403 && detail.includes('Artifact is not registered public')
}

function cloneOutline(outline: OutlineDocument): OutlineDocument {
  return JSON.parse(JSON.stringify(outline)) as OutlineDocument
}

function listToText(items: string[] | undefined): string {
  return (items ?? []).join('\n')
}

function textToList(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function outlineSignature(outline: OutlineDocument | null | undefined): string {
  return outline ? JSON.stringify(outline) : ''
}

function moduleCount(outline: OutlineDocument | null | undefined, module: OutlineModule): number {
  if (!outline) return 0
  if (module === 'sections') return outline.section_plan.length
  if (module === 'figures') return outline.plotting_plan.length
  if (module === 'literature') return outline.macro_lit_search.length + outline.micro_lit_clusters.length
  return Object.keys(outline.pathlab_extensions ?? {}).length
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <div className="text-xs font-semibold text-slate-500">{children}</div>
}

function TextInput({ value, editing, onChange }: { value: string; editing: boolean; onChange: (value: string) => void }) {
  if (!editing) return <div className="break-words text-sm leading-6 text-slate-800">{value || '-'}</div>
  return (
    <input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
    />
  )
}

function TextArea({ value, editing, onChange, rows = 3 }: { value: string; editing: boolean; onChange: (value: string) => void; rows?: number }) {
  if (!editing) return <div className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{value || '-'}</div>
  return (
    <textarea
      value={value}
      rows={rows}
      onChange={(event) => onChange(event.target.value)}
      className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
    />
  )
}

function ModuleShell({ children }: { children: ReactNode }) {
  return <div className="space-y-3">{children}</div>
}

export function OutlineTab({ paperId, run }: OutlineTabProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [selectedModule, setSelectedModule] = useState<OutlineModule>('sections')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<OutlineDocument | null>(null)
  const [saveNotice, setSaveNotice] = useState<string | null>(null)

  const outlineQuery = useQuery({
    queryKey: ['paper-file', paperId, 'drafts/outline.json'],
    queryFn: () => getPaperFileJson<OutlineDocument>(paperId, 'drafts/outline.json'),
    retry: false,
  })

  useEffect(() => {
    if (outlineQuery.data && !editing) setDraft(cloneOutline(outlineQuery.data))
  }, [editing, outlineQuery.data])

  const activeOutline = draft ?? outlineQuery.data ?? null
  const validation = useMemo(() => validateOutlineDocument(activeOutline), [activeOutline])
  const isMissing = artifactUnavailable(outlineQuery.error)
  const awaitingApproval = run.status === 'awaiting_outline_approval'
  const continuingAfterOutline = run.status === 'running' && POST_OUTLINE_STAGES.has(run.current_stage)
  const dirty = outlineSignature(draft) !== outlineSignature(outlineQuery.data)

  const updateDraft = (updater: (outline: OutlineDocument) => OutlineDocument) => {
    setDraft((current) => {
      if (!current) return current
      setSaveNotice(null)
      return updater(cloneOutline(current))
    })
  }

  const saveMutation = useMutation({
    mutationFn: async (approve: boolean) => {
      if (!activeOutline || !validateOutlineDocument(activeOutline)) throw new Error(t('paperAgent.outline.notLoadedError'))
      return putPaperOutline(paperId, { outline: activeOutline, approve })
    },
    onSuccess: async (_response, approve) => {
      if (activeOutline) queryClient.setQueryData(['paper-file', paperId, 'drafts/outline.json'], cloneOutline(activeOutline))
      await queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
      await queryClient.invalidateQueries({ queryKey: ['paper-file', paperId, 'drafts/outline.json'] })
      await queryClient.invalidateQueries({ queryKey: ['paper-file', paperId, 'drafts/大纲.md'] })
      setEditing(false)
      setSaveNotice(approve ? null : t('paperAgent.outline.saved'))
    },
  })

  const startEditing = () => {
    if (!outlineQuery.data) return
    setDraft(cloneOutline(outlineQuery.data))
    setEditing(true)
    setSaveNotice(null)
    saveMutation.reset()
  }

  const cancelEditing = () => {
    setDraft(outlineQuery.data ? cloneOutline(outlineQuery.data) : null)
    setEditing(false)
    saveMutation.reset()
  }

  const updateSection = (index: number, patch: Partial<SectionPlanItem>) => {
    updateDraft((outline) => {
      outline.section_plan[index] = { ...outline.section_plan[index], ...patch }
      return outline
    })
  }

  const updatePlot = (index: number, patch: Partial<PlottingPlanItem>) => {
    updateDraft((outline) => {
      outline.plotting_plan[index] = { ...outline.plotting_plan[index], ...patch }
      return outline
    })
  }

  const updateCluster = (index: number, patch: Partial<MicroLitCluster>) => {
    updateDraft((outline) => {
      outline.micro_lit_clusters[index] = { ...outline.micro_lit_clusters[index], ...patch }
      return outline
    })
  }

  if (outlineQuery.isLoading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.outline.loading')}</div>
  }

  if (isMissing) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <Braces className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.outline.emptyTitle')}</div>
          <p className="mt-1 text-sm text-slate-500">{t('paperAgent.outline.emptyDescription')}</p>
        </CardContent>
      </Card>
    )
  }

  if (outlineQuery.error) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{outlineQuery.error instanceof Error ? outlineQuery.error.message : String(outlineQuery.error)}</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-950">{t('paperAgent.outline.title')}</h2>
          <p className="text-sm text-slate-500">{t('paperAgent.outline.description')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {awaitingApproval ? <Badge variant="secondary">{t('paperAgent.outline.awaitingApproval')}</Badge> : null}
          {continuingAfterOutline ? <Badge variant="secondary">{t('paperAgent.outline.continuing', { stage: paperStageLabel(t, run.current_stage) })}</Badge> : null}
          {validation ? <Badge variant="secondary">OutlineDocument</Badge> : <Badge variant="destructive">{t('paperAgent.outline.schemaMismatch')}</Badge>}
          <Badge variant="outline">drafts/大纲.md</Badge>
        </div>
      </div>

      {awaitingApproval ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <div className="flex min-w-0 items-start gap-2">
            <PlayCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">{t('paperAgent.outline.readyTitle')}</div>
              <div className="mt-0.5 text-amber-800">{t('paperAgent.outline.readyDescription')}</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {!editing ? (
              <Button type="button" size="sm" variant="outline" className="gap-2 bg-white" onClick={startEditing} disabled={!validation || saveMutation.isPending}>
                <PencilLine className="h-4 w-4" />
                {t('paperAgent.common.edit')}
              </Button>
            ) : null}
            {editing ? (
              <>
                <Button type="button" size="sm" className="gap-2 bg-emerald-600 text-white hover:bg-emerald-500" onClick={() => saveMutation.mutate(false)} disabled={!dirty || saveMutation.isPending || !validation}>
                  {saveMutation.isPending && !saveMutation.variables ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {t('paperAgent.common.save')}
                </Button>
                <Button type="button" size="sm" variant="ghost" className="gap-2 border border-slate-200 bg-white" onClick={cancelEditing} disabled={saveMutation.isPending}>
                  <X className="h-4 w-4" />
                  {t('paperAgent.common.cancel')}
                </Button>
              </>
            ) : null}
            <Button type="button" size="sm" className="gap-2 bg-amber-900 text-white hover:bg-amber-950" onClick={() => saveMutation.mutate(true)} disabled={!validation || saveMutation.isPending}>
              {saveMutation.isPending && saveMutation.variables ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {t('paperAgent.outline.approve')}
            </Button>
          </div>
        </div>
      ) : null}

      {continuingAfterOutline ? (
        <div className="flex items-start gap-2 rounded-2xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800">
          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
          {t('paperAgent.outline.postOutlineRunning')}
        </div>
      ) : null}

      {saveNotice ? (
        <div className="flex items-start gap-2 rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          {saveNotice}
        </div>
      ) : null}

      {saveMutation.error ? (
        <div className="flex items-start gap-2 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {saveMutation.error instanceof Error ? saveMutation.error.message : String(saveMutation.error)}
        </div>
      ) : null}

      {!validation ? (
        <div className="space-y-3 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {t('paperAgent.outline.invalidSchema')}
          </div>
          <pre className="max-h-[50vh] overflow-auto rounded-xl bg-white p-3 text-xs text-slate-800">{JSON.stringify(outlineQuery.data, null, 2)}</pre>
        </div>
      ) : activeOutline ? (
        <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
          <nav className="rounded-2xl border border-slate-200 bg-slate-50/70 p-2">
            <div className="px-2 pb-2 text-xs font-semibold uppercase text-slate-400">{t('paperAgent.outline.modules')}</div>
            <div className="space-y-1">
              {MODULES.map((module) => {
                const Icon = module.icon
                const selected = selectedModule === module.id
                return (
                  <button
                    key={module.id}
                    type="button"
                    onClick={() => setSelectedModule(module.id)}
                    className={cn(
                      'flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm transition',
                      selected ? 'bg-slate-950 text-white shadow-sm' : 'text-slate-600 hover:bg-white hover:text-slate-950',
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="truncate">{t(`paperAgent.outline.moduleLabels.${module.id}`)}</span>
                    </span>
                    <span className={cn('rounded-full px-2 py-0.5 text-xs', selected ? 'bg-white/15 text-white' : 'bg-white text-slate-500')}>
                      {moduleCount(activeOutline, module.id)}
                    </span>
                  </button>
                )
              })}
            </div>
          </nav>

          <div className="min-w-0 rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50/80 px-4 py-3">
              <div>
                <div className="text-xs font-semibold uppercase text-slate-400">{t('paperAgent.outline.outlineEditor')}</div>
                <div className="font-semibold text-slate-950">{t(`paperAgent.outline.moduleLabels.${selectedModule}`)}</div>
              </div>
              <div className={cn('rounded-full px-2.5 py-1 text-xs', editing && dirty ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-500')}>
                {editing && dirty ? t('paperAgent.sections.unsavedChanges') : t('paperAgent.sections.noChanges')}
              </div>
            </div>
            <div className="max-h-[68vh] overflow-auto p-4">
              {selectedModule === 'sections' ? (
                <ModuleShell>
                  {activeOutline.section_plan.map((section, index) => (
                    <div key={`${section.section}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-slate-400">{t('paperAgent.outline.sectionName')}</div>
                          {editing ? (
                            <TextInput value={section.section} editing onChange={(value) => updateSection(index, { section: value })} />
                          ) : (
                            <div className="text-base font-semibold text-slate-950">{labelForSection(section.section, t)}</div>
                          )}
                        </div>
                        {editing ? (
                          <Button type="button" size="icon" variant="ghost" className="h-8 w-8 text-rose-600 hover:bg-rose-50" onClick={() => updateDraft((outline) => ({ ...outline, section_plan: outline.section_plan.filter((_, itemIndex) => itemIndex !== index) }))}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        <div className="md:col-span-2">
                          <FieldLabel>{t('paperAgent.outline.goal')}</FieldLabel>
                          <TextArea value={section.goal} editing={editing} onChange={(value) => updateSection(index, { goal: value })} />
                        </div>
                        <div>
                          <FieldLabel>{t('paperAgent.outline.evidenceInputs')}</FieldLabel>
                          <TextArea value={listToText(section.evidence_inputs)} editing={editing} onChange={(value) => updateSection(index, { evidence_inputs: textToList(value) })} />
                        </div>
                        <div>
                          <FieldLabel>{t('paperAgent.outline.citationHints')}</FieldLabel>
                          <TextArea value={listToText(section.citation_hints)} editing={editing} onChange={(value) => updateSection(index, { citation_hints: textToList(value) })} />
                        </div>
                        <div className="md:col-span-2">
                          <FieldLabel>{t('paperAgent.outline.lockedBlockInputs')}</FieldLabel>
                          <TextArea value={listToText(section.locked_block_inputs)} editing={editing} onChange={(value) => updateSection(index, { locked_block_inputs: textToList(value) })} />
                        </div>
                      </div>
                    </div>
                  ))}
                  {editing ? (
                    <Button type="button" variant="outline" className="gap-2 bg-white" onClick={() => updateDraft((outline) => ({ ...outline, section_plan: [...outline.section_plan, { section: 'new_section', goal: '', evidence_inputs: [], citation_hints: [], locked_block_inputs: [] }] }))}>
                      <Plus className="h-4 w-4" />
                      {t('paperAgent.outline.addSection')}
                    </Button>
                  ) : null}
                </ModuleShell>
              ) : null}

              {selectedModule === 'figures' ? (
                <ModuleShell>
                  {activeOutline.plotting_plan.map((figure, index) => (
                    <div key={`${figure.figure_id}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <FieldLabel>{t('paperAgent.outline.figureId')}</FieldLabel>
                          <TextInput value={figure.figure_id} editing={editing} onChange={(value) => updatePlot(index, { figure_id: value })} />
                        </div>
                        {editing ? (
                          <Button type="button" size="icon" variant="ghost" className="h-8 w-8 text-rose-600 hover:bg-rose-50" onClick={() => updateDraft((outline) => ({ ...outline, plotting_plan: outline.plotting_plan.filter((_, itemIndex) => itemIndex !== index) }))}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        <div><FieldLabel>{t('paperAgent.outline.kind')}</FieldLabel><TextInput value={figure.kind} editing={editing} onChange={(value) => updatePlot(index, { kind: value })} /></div>
                        <div><FieldLabel>{t('paperAgent.outline.backend')}</FieldLabel><TextInput value={figure.backend} editing={editing} onChange={(value) => updatePlot(index, { backend: value })} /></div>
                        <div className="md:col-span-2"><FieldLabel>{t('paperAgent.outline.source')}</FieldLabel><TextArea value={figure.source} editing={editing} onChange={(value) => updatePlot(index, { source: value })} /></div>
                        <div className="md:col-span-2"><FieldLabel>{t('paperAgent.outline.designObjective')}</FieldLabel><TextArea value={figure.design_objective} editing={editing} onChange={(value) => updatePlot(index, { design_objective: value })} /></div>
                      </div>
                    </div>
                  ))}
                  {editing ? (
                    <Button type="button" variant="outline" className="gap-2 bg-white" onClick={() => updateDraft((outline) => ({ ...outline, plotting_plan: [...outline.plotting_plan, { figure_id: 'new_figure', kind: '', source: '', design_objective: '', backend: '', plot_spec: {} }] }))}>
                      <Plus className="h-4 w-4" />
                      {t('paperAgent.outline.addFigure')}
                    </Button>
                  ) : null}
                </ModuleShell>
              ) : null}

              {selectedModule === 'literature' ? (
                <ModuleShell>
                  <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                    <FieldLabel>{t('paperAgent.outline.macroLitSearch')}</FieldLabel>
                    <TextArea value={listToText(activeOutline.macro_lit_search)} editing={editing} rows={5} onChange={(value) => updateDraft((outline) => ({ ...outline, macro_lit_search: textToList(value) }))} />
                  </div>
                  {activeOutline.micro_lit_clusters.map((cluster, index) => (
                    <div key={`${cluster.cluster}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <FieldLabel>{t('paperAgent.outline.cluster')}</FieldLabel>
                          <TextInput value={cluster.cluster} editing={editing} onChange={(value) => updateCluster(index, { cluster: value })} />
                        </div>
                        {editing ? (
                          <Button type="button" size="icon" variant="ghost" className="h-8 w-8 text-rose-600 hover:bg-rose-50" onClick={() => updateDraft((outline) => ({ ...outline, micro_lit_clusters: outline.micro_lit_clusters.filter((_, itemIndex) => itemIndex !== index) }))}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-3">
                        <FieldLabel>{t('paperAgent.outline.queries')}</FieldLabel>
                        <TextArea value={listToText(cluster.queries)} editing={editing} onChange={(value) => updateCluster(index, { queries: textToList(value) })} />
                      </div>
                    </div>
                  ))}
                  {editing ? (
                    <Button type="button" variant="outline" className="gap-2 bg-white" onClick={() => updateDraft((outline) => ({ ...outline, micro_lit_clusters: [...outline.micro_lit_clusters, { cluster: 'new_topic', queries: [] }] }))}>
                      <Plus className="h-4 w-4" />
                      {t('paperAgent.outline.addCluster')}
                    </Button>
                  ) : null}
                </ModuleShell>
              ) : null}

              {selectedModule === 'extensions' ? (
                <ModuleShell>
                  <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                    <FieldLabel>{t('paperAgent.outline.templates')}</FieldLabel>
                    <TextArea value={listToText(activeOutline.pathlab_extensions.templates)} editing={editing} onChange={(value) => updateDraft((outline) => ({ ...outline, pathlab_extensions: { ...outline.pathlab_extensions, templates: textToList(value) } }))} />
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                    <FieldLabel>{t('paperAgent.outline.guardRequirements')}</FieldLabel>
                    <TextArea value={listToText(activeOutline.pathlab_extensions.guard_requirements)} editing={editing} onChange={(value) => updateDraft((outline) => ({ ...outline, pathlab_extensions: { ...outline.pathlab_extensions, guard_requirements: textToList(value) } }))} />
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                    <FieldLabel>{t('paperAgent.outline.extensionJson')}</FieldLabel>
                    <pre className="mt-2 max-h-[360px] overflow-auto rounded-lg bg-white p-3 text-xs text-slate-700">{JSON.stringify(activeOutline.pathlab_extensions, null, 2)}</pre>
                  </div>
                </ModuleShell>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
