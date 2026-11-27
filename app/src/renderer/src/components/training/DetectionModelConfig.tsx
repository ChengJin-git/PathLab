import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { fetchTrainingOptions } from '../../api/trainingOptions'
import { FEATURE_EXTRACTORS } from '../../constants/training'
import { Select } from '../ui/select'
import { Checkbox } from '../ui/checkbox'

export interface DetectionModelOptions {
  architecture: 'fasterrcnn' | 'retinanet' | 'fcos'
  backbone: string
  pretrained: boolean
  train_backbone: boolean
  image_size: number
  max_detections: number
}

export const defaultDetectionOptions: DetectionModelOptions = {
  architecture: 'fasterrcnn', backbone: 'resnet50', pretrained: true,
  train_backbone: true, image_size: 512, max_detections: 100,
}

export default function DetectionModelConfig({ value, onChange }: {
  value: DetectionModelOptions
  onChange: (value: DetectionModelOptions) => void
}) {
  const { t } = useTranslation()
  const options = useQuery({ queryKey: ['training-options'], queryFn: () => fetchTrainingOptions(), staleTime: 300000 })
  const update = (patch: Partial<DetectionModelOptions>) => onChange({ ...value, ...patch })
  const foundation = !['resnet18', 'resnet34', 'resnet50', 'resnet101'].includes(value.backbone)
  return <div className="space-y-5">
    <p className="text-sm text-slate-600">{t('detection.description')}</p>
    <label className="block space-y-2 text-sm font-medium">
      <span>{t('detection.architecture')}</span>
      <Select ariaLabel={t('detection.architecture')} value={value.architecture}
        onChange={architecture => update({ architecture: architecture as DetectionModelOptions['architecture'] })}
        options={options.data?.detection_architectures?.map(item => ({ value: item.id, label: item.name })) || [{ value: 'fasterrcnn', label: 'Faster R-CNN' }, { value: 'retinanet', label: 'RetinaNet' }, { value: 'fcos', label: 'FCOS' }]} />
    </label>
    <label className="block space-y-2 text-sm font-medium">
      <span>{t('detection.backbone')}</span>
      <Select ariaLabel={t('detection.backbone')} value={value.backbone} onChange={backbone => update({ backbone, pretrained: true })}
        options={options.data?.detection_backbones?.map(item => ({ value: item.id, label: `${item.name} · ${item.group}` })) || [
          ...['resnet18', 'resnet34', 'resnet50', 'resnet101'].map(name => ({ value: name, label: name })),
          ...FEATURE_EXTRACTORS.filter(item => item.supports_spatial).map(item => ({ value: item.id, label: `${item.name} · Foundation model` })),
        ]} />
    </label>
    <label className="flex items-center gap-3 text-sm">
      <Checkbox checked={value.train_backbone} onCheckedChange={checked => update({ train_backbone: !!checked })} />
      {t('detection.finetune')}
    </label>
    {!foundation && <label className="flex items-center gap-3 text-sm">
      <Checkbox checked={value.pretrained} onCheckedChange={checked => update({ pretrained: !!checked })} />
      {t('detection.pretrained')}
    </label>}
    <div className="grid grid-cols-2 gap-3">
      <label className="space-y-2 text-sm">{t('detection.imageSize')}
        <input className="w-full rounded-lg border p-2" type="number" min={64} max={2048} step={32} value={value.image_size}
          onChange={e => update({ image_size: Number(e.target.value) })} />
      </label>
      <label className="space-y-2 text-sm">{t('detection.maxDetections')}
        <input className="w-full rounded-lg border p-2" type="number" min={1} max={1000} value={value.max_detections}
          onChange={e => update({ max_detections: Number(e.target.value) })} />
      </label>
    </div>
  </div>
}
