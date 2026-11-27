import { useEffect, useState } from 'react'
import { fetchAvailableHeatmaps, getThumbnailUrl, getPatchCAMImageUrl, getHeatmapThumbnailUrl, type AvailableHeatmap } from '../../../api/heatmap'
import { apiFetchBlob } from '../../../api/client'
import { resultBase } from '../../../api/resultWorkbench'
import DetectionPreview, { type DetectionSample } from './DetectionPreview'
import { useResultText } from './text'
import { Select } from '../../ui/select'

export interface PreviewSample {
  source_id: string
  task_id?: string
  fold_key?: string
  task_type: string
  wsi_id: string
  filename?: string
  classes: string[]
  label?: string
  pred?: string
  probs?: Record<string, number>
  segmentation_preview?: boolean
  has_ground_truth?: boolean
  metrics?: Record<string, number>
  risk_score?: number
  event_time?: number
  event_status?: number
}

function MaskPreview({ sample, analysisId, threshold }: { sample: PreviewSample; analysisId: string; threshold: number }) {
  const { text } = useResultText()
  const [category, setCategory] = useState('0')
  const [layer, setLayer] = useState('pred')
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''
    setUrl(''); setError('')
    setLoading(true)
    const query = new URLSearchParams({ source_id: sample.source_id, wsi_id: sample.wsi_id, layer, class_index: category })
    apiFetchBlob(`${resultBase()}/runs/${analysisId}/preview?${query}`, { signal: controller.signal })
      .then(blob => { if (!controller.signal.aborted) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) } })
      .catch(err => { if (!controller.signal.aborted) setError(String(err)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [sample.source_id, sample.wsi_id, sample.segmentation_preview, analysisId, category, layer])
  return <div className="space-y-3">
    <div className="flex flex-wrap gap-3">
      <Select ariaLabel={text('positive')} value={category} onChange={setCategory} options={sample.classes.map((name, i) => ({ value: String(i), label: name }))} />
      <Select ariaLabel={text('previewLayer')} value={layer} onChange={setLayer} options={[
        { value: 'pred', label: `${text('predicted')} > ${threshold.toFixed(2)}` },
        { value: 'gt', label: text('actual'), disabled: !sample.has_ground_truth },
      ]} />
    </div>
    <div className="relative mx-auto w-fit max-w-full">
      <img src={getThumbnailUrl(sample.wsi_id, 768)} className="max-h-[420px] max-w-full" alt={sample.filename || sample.wsi_id} />
      {url && <img src={url} className="absolute inset-0 h-full w-full" alt={text('previewLayer')} />}
    </div>
    {loading && <p role="status" className="text-xs">{text('loading')}</p>}
    {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
    {!sample.segmentation_preview && <p className="text-xs text-slate-500">{text('thresholdUnavailable')}</p>}
    <p className="text-xs text-slate-600">{Object.entries(sample.metrics || {}).map(([key, value]) => `${key}: ${Number(value).toFixed(3)}`).join(' · ')}</p>
  </div>
}

export default function SamplePreview({ sample, analysisId, threshold }: { sample: PreviewSample; analysisId: string; threshold: number }) {
  const { text } = useResultText()
  const [open, setOpen] = useState(false)
  if (!sample.wsi_id) return null
  if (!['patch_detection', 'patch_segmentation', 'patch_classification', 'wsi_classification', 'wsi_survival'].includes(sample.task_type)) return null
  return <details className="rounded-xl border p-3" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-sm font-medium">{sample.filename || sample.wsi_id} · {text('samplePreview')}</summary>
    {open && <div className="mt-4">
      {sample.task_type === 'patch_detection' ? <DetectionPreview sample={sample as unknown as DetectionSample} threshold={threshold} />
        : sample.task_type === 'patch_segmentation' ? <><MaskPreview sample={sample} analysisId={analysisId} threshold={threshold} /><AttentionPreview sample={sample} /></>
        : <div className="space-y-3">
          <img src={getThumbnailUrl(sample.wsi_id, 384)} alt={sample.filename || sample.wsi_id} className="max-h-60 max-w-full rounded" />
          {sample.task_type === 'wsi_survival'
            ? <p className="text-xs">{text('riskScore')}: {sample.risk_score?.toFixed(4) ?? '—'} · {text('actual')}: {sample.event_time ?? '—'} / {sample.event_status ?? '—'}</p>
            : <p className="text-xs">{text('actual')}: {sample.label || '—'} · {text('predicted')}: {sample.pred || '—'}{sample.classes.length === 2 ? ` · ${text('threshold')}: ${threshold.toFixed(2)}` : ''}</p>}
          {Object.entries(sample.probs || {}).map(([name, probability]) => <div key={name} className="text-xs">
            <span>{name}: {(probability * 100).toFixed(1)}%</span><progress className="mt-1 h-2 w-full" max={1} value={probability} />
          </div>)}
          <AttentionPreview sample={sample} />
        </div>}
    </div>}
  </details>
}

function AttentionPreview({ sample }: { sample: PreviewSample }) {
  const { text } = useResultText()
  const [available, setAvailable] = useState<AvailableHeatmap | null>(null)
  const [show, setShow] = useState(false)
  useEffect(() => {
    let cancelled = false
    fetchAvailableHeatmaps(sample.wsi_id).then(entries => {
      if (!cancelled) setAvailable(entries.find(entry => entry.task_id === sample.task_id && (entry.fold_key || undefined) === sample.fold_key && entry.has_heatmap !== false) || null)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [sample.wsi_id, sample.task_id, sample.fold_key])
  if (!available || !sample.task_id) return null
  return <div>
    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={show} onChange={event => setShow(event.target.checked)} />{text('attentionPreview')}</label>
    {show && <img className="mt-3 max-h-80 max-w-full" alt={text('attentionPreview')} src={sample.task_type.startsWith('patch_')
      ? getPatchCAMImageUrl(sample.wsi_id, sample.task_id, sample.fold_key, 512)
      : getHeatmapThumbnailUrl(sample.wsi_id, sample.task_id, 512, undefined, sample.fold_key)} />}
  </div>
}
