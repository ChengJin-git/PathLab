import { useState } from 'react'
import { getThumbnailUrl } from '../../../api/heatmap'
import { useResultText } from './text'

interface Boxes { boxes: number[][]; labels: number[]; scores?: number[] }
export interface DetectionSample {
  wsi_id: string
  filename?: string
  image_size?: [number, number]
  classes: string[]
  detection: { prediction: Boxes; target: Boxes | null }
}

export default function DetectionPreview({ sample, threshold }: { sample: DetectionSample; threshold: number }) {
  const { text } = useResultText()
  const [showTruth, setShowTruth] = useState(true)
  const [showPrediction, setShowPrediction] = useState(true)
  const [width, height] = sample.image_size || [1, 1]
  const render = (boxes: Boxes, prediction: boolean) => boxes.boxes.map((box, i) => {
    if (prediction && (boxes.scores?.[i] ?? 0) < threshold) return null
    return <rect key={i} x={box[0]} y={box[1]} width={box[2] - box[0]} height={box[3] - box[1]}
      fill="none" stroke={prediction ? '#e11d48' : '#16a34a'} strokeWidth={2} vectorEffect="non-scaling-stroke"
      strokeDasharray={prediction ? undefined : '5 3'}>
      <title>{sample.classes[boxes.labels[i] - 1]}{prediction ? ` · ${((boxes.scores?.[i] ?? 0) * 100).toFixed(1)}%` : ''}</title>
    </rect>
  })
  return <div className="rounded-xl border p-3">
    <div className="mb-3 flex flex-wrap items-center gap-4 text-xs">
      <span className="font-medium">{sample.filename || sample.wsi_id}</span>
      <label className="flex items-center gap-2 text-green-700"><input type="checkbox" checked={showTruth} onChange={e => setShowTruth(e.target.checked)} />{text('actual')}</label>
      <label className="flex items-center gap-2 text-rose-600"><input type="checkbox" checked={showPrediction} onChange={e => setShowPrediction(e.target.checked)} />{text('predicted')} ≥ {threshold.toFixed(2)}</label>
    </div>
    {sample.image_size && <svg className="max-h-[420px] w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={sample.filename || sample.wsi_id}>
      <image href={getThumbnailUrl(sample.wsi_id, 768)} width={width} height={height} preserveAspectRatio="none" />
      {showTruth && sample.detection.target && render(sample.detection.target, false)}
      {showPrediction && render(sample.detection.prediction, true)}
    </svg>}
    {!sample.image_size && <div className="max-h-60 overflow-auto text-xs">
      {sample.detection.prediction.boxes.map((box, index) => (sample.detection.prediction.scores?.[index] ?? 0) >= threshold && <p key={index}>
        {sample.classes[sample.detection.prediction.labels[index] - 1]} · {box.map(value => value.toFixed(1)).join(', ')} · {((sample.detection.prediction.scores?.[index] ?? 0) * 100).toFixed(1)}%
      </p>)}
    </div>}
  </div>
}
