import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, Check, ChevronDown, CircleHelp, Database, FileCode2,
  Loader2, Plus, ShieldCheck, Upload,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  continueResearch, getResearchDatasets, listResearchSourceFiles,
  readResearchFile, saveResearchSource,
} from '../../api/autoresearch'
import type { ResearchDataset, ResearchRecovery } from '../../types/autoresearch'
import { Button } from '../ui/button'
import { Checkbox } from '../ui/checkbox'
import { Input } from '../ui/input'
import { Select } from '../ui/select'

export default function ResearchRecoveryPanel({ sessionId, recovery, workspaceId, onContinued }: {
  sessionId: string
  recovery?: ResearchRecovery | null
  workspaceId?: string
  onContinued: () => Promise<void>
}) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith('zh'), hk = /zh-(HK|TW|Hant)/i.test(i18n.language)
  const copy = (en: string, cn: string, tw = cn) => zh ? hk ? tw : cn : en
  const titleId = useId()
  const inputId = useId()
  const replaceId = useId()
  const [text, setText] = useState('')
  const [datasets, setDatasets] = useState<ResearchDataset[]>()
  const [datasetId, setDatasetId] = useState('')
  const [extraExperiments, setExtraExperiments] = useState(0)
  const [extraHours, setExtraHours] = useState('')
  const [replaceDatasets, setReplaceDatasets] = useState(false)
  const [sourceFiles, setSourceFiles] = useState<string[]>()
  const [editor, setEditor] = useState<{ path: string; content: string; revision: string }>()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const reason = recovery?.reason || 'other'
  const reasons: Record<string, { label: string; description: string }> = {
    missing_data: {
      label: copy('Data or files', '数据或文件', '資料或檔案'),
      description: copy('Some required data or files are missing.', '缺少必要的数据或文件。', '缺少必要的資料或檔案。'),
    },
    data_access: {
      label: copy('Resource access', '资源访问', '資源存取'),
      description: copy('A dataset or resource is not currently accessible.', '目前无法访问所需的数据或资源。', '目前無法存取所需資料或資源。'),
    },
    data_preparation: {
      label: copy('Input preparation', '输入数据准备', '輸入資料準備'),
      description: copy('Input preparation did not finish. Previously prepared inputs and research results are saved; check the storage details below.', '输入数据准备未完成。已准备的输入与研究结果均已保留，请查看下方存储检查详情。', '輸入資料準備未完成。已準備的輸入與研究結果均已保留，請查看下方儲存檢查詳情。'),
    },
    code_error: {
      label: copy('Code execution', '代码执行', '程式執行'),
      description: copy('The code could not complete this step.', '代码未能完成当前步骤。', '程式未能完成目前步驟。'),
    },
    service: {
      label: copy('Service availability', '服务可用性', '服務可用性'),
      description: copy('A service request did not complete. Check the details below for the affected component.', '一次服务请求未完成，请查看下方详情确认受影响的组件。', '一次服務請求未完成，請查看下方詳情確認受影響的元件。'),
    },
    budget: {
      label: copy('Time or experiment budget', '时间或实验预算', '時間或實驗預算'),
      description: copy('This run reached its time or experiment budget.', '本轮已达到时间或实验预算。', '本輪已達時間或實驗預算。'),
    },
    needs_input: {
      label: copy('Information or decision', '信息或方向确认', '資訊或方向確認'),
      description: copy('A detail or decision is needed before continuing.', '继续之前需要补充信息或确认方向。', '繼續之前需要補充資訊或確認方向。'),
    },
    direction: {
      label: copy('Research direction', '研究方向选择', '研究方向選擇'),
      description: copy('The planned routes did not reach the publication bar. Review the results and options below, then choose how to continue.', '已规划的路线未达到发表门槛。请查看下方结果与可选路线，并决定如何继续。', '已規劃的路線未達到發表門檻。請查看下方結果與可選路線，並決定如何繼續。'),
    },
    other: {
      label: copy('Next step', '下一步处理', '下一步處理'),
      description: copy('This task needs attention before it can continue.', '当前任务需要处理一个问题后才能继续。', '目前任務需要處理一個問題後才能繼續。'),
    },
  }
  const issue = reasons[reason] || reasons.other
  // Choosing a new research route usually needs more time as well as attempts.
  const budgetReason = reason === 'budget' || reason === 'direction'
  const run = async (operation: string, fn: () => Promise<unknown>) => {
    setBusy(operation); setError(''); setNotice('')
    try { await fn() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy('') }
  }
  const assistanceTools = <>
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm" className="min-h-10 cursor-pointer gap-2">
        <Link to="/upload"><Upload size={14} aria-hidden="true" />{copy('Upload data', '上传数据', '上傳資料')}</Link>
      </Button>
      <Button type="button" variant="outline" size="sm" className="min-h-10 cursor-pointer gap-2" disabled={!!busy} onClick={() => void run('datasets', async () => {
        const result = await getResearchDatasets('', workspaceId)
        setDatasets(result.items)
      })}>
        {busy === 'datasets' ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <Database size={14} />}
        {copy('Attach Data Repo dataset', '补充数据仓库数据', '補充資料倉庫資料')}
      </Button>
      <Button type="button" variant="outline" size="sm" className="min-h-10 cursor-pointer gap-2" disabled={!!busy} onClick={() => void run('sources', async () => {
        setSourceFiles((await listResearchSourceFiles(sessionId)).items)
      })}>
        {busy === 'sources' ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <FileCode2 size={14} />}
        {copy('Edit workspace code', '修改工作区代码', '修改工作區程式')}
      </Button>
    </div>
    {datasets && <div className="mt-4 space-y-2">
      <p className="text-xs font-medium text-slate-700">{copy('Dataset to attach', '补充的数据集', '補充的資料集')}</p>
      <Select ariaLabel={copy('Dataset to attach', '补充的数据集', '補充的資料集')} value={datasetId} onChange={setDatasetId} disabled={!!busy}
        placeholder={copy('Select a dataset…', '选择数据集…', '選擇資料集…')}
        options={datasets.map(d => ({ value: d.dataset_id, label: `${d.name} · ${d.file_count}` }))} />
      {datasets.length === 0 && <p className="text-xs text-slate-600">{copy('No accessible datasets in this workspace.', '当前工作区没有可选的数据集。', '目前工作區沒有可選的資料集。')}</p>}
      {datasetId && <div className="flex items-center gap-2 pt-1">
        <Checkbox id={replaceId} checked={replaceDatasets} onCheckedChange={setReplaceDatasets} disabled={!!busy} />
        <label htmlFor={replaceId} className="cursor-pointer text-xs leading-5 text-slate-600">{copy('Use this dataset instead of the previous inputs', '用该数据集替换原有输入', '用此資料集替換原有輸入')}</label>
      </div>}
    </div>}
    {sourceFiles && <div className="mt-4 space-y-2">
      <p className="text-xs font-medium text-slate-700">{copy('Source file', '源码文件', '原始碼檔案')}</p>
      <Select ariaLabel={copy('Source file', '源码文件', '原始碼檔案')} value={editor?.path || ''} disabled={!!busy}
        onChange={path => void run('read', async () => setEditor(await readResearchFile(sessionId, path)))}
        placeholder={copy('Choose a file…', '选择文件…', '選擇檔案…')} options={sourceFiles.map(value => ({ value, label: value }))} />
      {sourceFiles.length === 0 && <p className="text-xs leading-5 text-slate-600">{copy('No editable sources yet. Describe the change below so the assistant can help.', '暂无可编辑源码，可在下方说明需要助手修改什么。', '暫無可編輯原始碼，可在下方說明需要助手修改甚麼。')}</p>}
    </div>}
    {editor && <div className="mt-3 space-y-2">
      <textarea aria-label={copy('Source editor', '源码编辑器', '原始碼編輯器')} value={editor.content}
        onChange={e => setEditor({ ...editor, content: e.target.value })} spellCheck={false} rows={10} disabled={!!busy}
        className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-6 text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400" />
      <Button type="button" variant="outline" size="sm" className="cursor-pointer" disabled={!!busy} onClick={() => void run('save', async () => {
        const result = await saveResearchSource(sessionId, editor.path, editor.content, editor.revision)
        setEditor({ ...editor, revision: result.revision })
        setNotice(copy('Saved. Continue when you are ready to use the updated source.', '源码已保存，准备好后可继续任务。', '原始碼已儲存，準備好後可繼續任務。'))
      })}>{copy('Save file', '保存文件', '儲存檔案')}</Button>
    </div>}
  </>

  return <section aria-labelledby={titleId} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="flex items-start gap-3 border-b border-slate-100 p-4 sm:p-5">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-700"><CircleHelp size={21} aria-hidden="true" /></div>
      <div className="min-w-0 flex-1">
        <h2 id={titleId} className="text-base font-semibold leading-6 text-slate-900">{copy('The assistant needs further assistance', '助手需要进一步协助', '助手需要進一步協助')}</h2>
        <p className="mt-1 text-xs leading-5 text-slate-600">{copy('Progression is paused. Resolve the issue or add guidance to continue.', '推进已暂停，处理阻塞或补充说明后即可继续。', '推進已暫停，處理阻礙或補充說明後即可繼續。')}</p>
      </div>
      <span className="hidden shrink-0 items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 sm:inline-flex"><Check size={12} />{copy('Progress saved', '进度已保存', '進度已儲存')}</span>
    </header>
    <div className="space-y-5 p-4 sm:p-5">
      <div>
        <span className="inline-block rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">{issue.label}</span>
        <p className="mt-2.5 whitespace-pre-wrap break-words text-sm leading-7 text-slate-800">{recovery?.summary || issue.description}</p>
        {recovery?.detail && <details className="group mt-2 text-xs text-slate-600">
          <summary className="inline-flex min-h-9 cursor-pointer list-none items-center gap-1.5 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400 [&::-webkit-details-marker]:hidden"><ChevronDown size={14} className="transition-transform group-open:rotate-180" />{copy('Technical details', '技术详情', '技術詳情')}</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-6">{recovery.detail}</pre>
        </details>}
      </div>
      {!!recovery?.next_steps?.length && <div>
        <h3 className="mb-2 text-xs font-semibold text-slate-700">{copy('Suggested next steps', '建议的下一步', '建議的下一步')}</h3>
        <ol className="space-y-2">{recovery.next_steps.map((step, index) => <li key={index} className="flex items-start gap-2.5 text-sm leading-6 text-slate-700">
          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-medium text-slate-500">{index + 1}</span><span className="min-w-0 break-words">{step}</span>
        </li>)}</ol>
      </div>}
      <div className="flex items-start gap-2 rounded-xl bg-slate-50 px-3 py-2.5 text-xs leading-5 text-slate-600">
        <ShieldCheck size={16} className="mt-0.5 shrink-0 text-slate-500" aria-hidden="true" />
        <p>{copy('Files, results and conversation are saved. Continue in this task; no need to start over. Already submitted jobs can still finish.', '文件、结果和对话已保留，无需重新创建任务。已提交的后台作业可继续完成。', '檔案、結果和對話已保留，無需重新建立任務。已提交的背景作業可繼續完成。')}</p>
      </div>
      {['missing_data', 'data_access', 'code_error'].includes(reason) ? <div>{assistanceTools}</div> : <details className="group">
        <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 rounded text-xs font-medium text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400 [&::-webkit-details-marker]:hidden"><Plus size={15} />{copy('Attach data or edit code', '补充数据或修改代码', '補充資料或修改程式')}<ChevronDown size={14} className="ml-auto transition-transform group-open:rotate-180" /></summary>
        <div className="pt-2">{assistanceTools}</div>
      </details>}
      <div>
        <label htmlFor={inputId} className="block text-xs font-semibold text-slate-700">{copy('Additional guidance', '补充说明', '補充說明')} <span className="font-normal text-slate-500">{copy('(optional)', '（可选）', '（可選）')}</span></label>
        <textarea id={inputId} value={text} onChange={e => setText(e.target.value)} rows={3} maxLength={12000} disabled={!!busy}
          placeholder={copy('Describe what has changed, clarify a decision, adjust the goal, or ask the assistant to investigate.', '说明已处理的问题、补充信息、调整目标，或请助手进一步排查。', '說明已處理的問題、補充資訊、調整目標，或請助手進一步排查。')}
          className="mt-2 w-full rounded-xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-800 placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400" />
      </div>
      <details open={budgetReason || undefined} className="group border-t border-slate-100 pt-2">
        <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 rounded text-xs font-medium text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400 [&::-webkit-details-marker]:hidden"><ChevronDown size={14} className="transition-transform group-open:rotate-180" />{copy('Adjust continuation budget', '调整继续执行的预算', '調整繼續執行的預算')}</summary>
        <div className="space-y-3 pt-2">
          {budgetReason && <p className="text-xs leading-6 text-slate-600">{t('reports.budgetHint')}</p>}
          <label className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-600">{copy('Additional experiment attempts (optional)', '追加实验次数（可选）', '追加實驗次數（可選）')}<Input type="number" min={0} max={20} value={extraExperiments} disabled={!!busy} onChange={e => setExtraExperiments(Math.max(0, Math.min(20, Number(e.target.value))))} className="w-24" /></label>
          {budgetReason && <>
            <label className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-600">{t('reports.resumeTime')}<Input type="number" min={0.1} max={72} step={0.5} value={extraHours} disabled={!!busy} onChange={e => setExtraHours(e.target.value === '' ? '' : String(Math.max(.1, Math.min(72, Number(e.target.value)))))} className="w-24" /></label>
            <p className="text-xs text-slate-500">{copy('Optional. Leave blank to keep the configured time allowance; enter a value to replace it.', '可选。留空沿用已配置的时间额度，填写后将替换该额度。', '可選。留空沿用已配置的時間額度，填寫後將替換該額度。')}</p>
          </>}
        </div>
      </details>
      {error && <p role="alert" className="break-words text-sm text-red-700">{error}</p>}
      {notice && <p role="status" className="text-xs leading-6 text-emerald-700">{notice}</p>}
    </div>
    <footer className="flex flex-col gap-3 border-t border-slate-100 bg-slate-50/60 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <span className="text-xs leading-5 text-slate-600">{copy('Continue when you are ready. The assistant will resume from saved progress.', '准备好后继续，助手会沿用已保存的进度。', '準備好後繼續，助手會沿用已儲存的進度。')}</span>
      <Button type="button" disabled={!!busy} className="min-h-11 shrink-0 cursor-pointer gap-2" onClick={() => void run('continue', async () => {
        await continueResearch(sessionId, { text, dataset_ids: datasetId ? [datasetId] : [], additional_experiments: extraExperiments,
          replace_datasets: replaceDatasets, ...(budgetReason && extraHours !== '' ? { additional_time_seconds: Math.round(Number(extraHours) * 3600) } : {}) })
        await onContinued()
      })}>
        {busy === 'continue' ? <Loader2 className="animate-spin motion-reduce:animate-none" size={16} /> : <ArrowRight size={16} />}
        {copy('Continue task', '继续任务', '繼續任務')}
      </Button>
    </footer>
  </section>
}
