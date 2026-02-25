import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Trash2, PackagePlus, ChevronDown, ChevronUp } from 'lucide-react'
import { AnnotationRegion, AnnotationsMap } from '../../api/annotation'
import { Card } from '../common'

interface AnnotationListPanelProps {
  currentWsiId: string
  regions: AnnotationRegion[]
  allAnnotations: AnnotationsMap
  labelColors: Record<string, string>
  onUpdateRegion: (regionId: string, updates: Partial<AnnotationRegion>) => void
  onDeleteRegion: (regionId: string) => void
  onCreateDataset: () => void
}

export function AnnotationListPanel({
  currentWsiId,
  regions,
  allAnnotations,
  labelColors,
  onUpdateRegion,
  onDeleteRegion,
  onCreateDataset,
}: AnnotationListPanelProps) {
  const { t } = useTranslation()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [showSummary, setShowSummary] = useState(true)

  // Cross-slide summary: total ROIs per label
  const summary = useMemo(() => {
    const counts: Record<string, { total: number; slides: Set<string> }> = {}
    for (const [wsiId, regs] of Object.entries(allAnnotations)) {
      for (const r of regs) {
        if (!counts[r.label]) counts[r.label] = { total: 0, slides: new Set() }
        counts[r.label].total++
        counts[r.label].slides.add(wsiId)
      }
    }
    return counts
  }, [allAnnotations])

  const totalRegions = useMemo(() => {
    return Object.values(allAnnotations).reduce((sum, regs) => sum + regs.length, 0)
  }, [allAnnotations])

  const totalSlides = useMemo(() => {
    return Object.keys(allAnnotations).filter(k => allAnnotations[k].length > 0).length
  }, [allAnnotations])

  const handleStartEdit = (region: AnnotationRegion) => {
    setEditingId(region.id)
    setEditLabel(region.label)
  }

  const handleSaveEdit = (regionId: string) => {
    if (editLabel.trim()) {
      onUpdateRegion(regionId, { label: editLabel.trim() })
    }
    setEditingId(null)
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Current slide annotations */}
      <Card className="overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
          <Pencil className="w-4 h-4 text-indigo-500" />
          <h3 className="m-0 text-sm font-semibold text-gray-900">{t('annotation.currentSlide')}</h3>
          <span className="ml-auto text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
            {regions.length} {t('annotation.regions')}
          </span>
        </div>
        <div className="p-3 max-h-[300px] overflow-y-auto">
          {regions.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-6">{t('annotation.noAnnotations')}</p>
          ) : (
            <div className="space-y-1.5">
              {regions.map((region, idx) => (
                <div key={region.id} className="flex items-center gap-2 px-2.5 py-2 bg-gray-50 rounded-lg group hover:bg-gray-100 transition-colors">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 border border-gray-200" style={{ backgroundColor: labelColors[region.label] || region.color }} />
                  {editingId === region.id ? (
                    <input
                      type="text"
                      value={editLabel}
                      onChange={e => setEditLabel(e.target.value)}
                      onBlur={() => handleSaveEdit(region.id)}
                      onKeyDown={e => { if (e.key === 'Enter') handleSaveEdit(region.id); if (e.key === 'Escape') setEditingId(null) }}
                      className="flex-1 px-1.5 py-0.5 text-xs border border-indigo-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none"
                      autoFocus
                    />
                  ) : (
                    <span className="flex-1 text-xs text-gray-700 truncate">{region.label}</span>
                  )}
                  <span className="text-[10px] text-gray-400">{region.type === 'polygon' ? '⬠' : '▭'} #{idx + 1}</span>
                  <span className="text-[10px] text-gray-400">{Math.round(region.width)}×{Math.round(region.height)}</span>
                  <button onClick={() => handleStartEdit(region)} className="p-1 text-gray-400 hover:text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity" title={t('annotation.editLabel')}>
                    <Pencil className="w-3 h-3" />
                  </button>
                  <button onClick={() => onDeleteRegion(region.id)} className="p-1 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity" title={t('annotation.deleteRegion')}>
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* Cross-slide summary */}
      <Card className="overflow-hidden">
        <button
          onClick={() => setShowSummary(!showSummary)}
          className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white w-full text-left"
        >
          <PackagePlus className="w-4 h-4 text-emerald-500" />
          <h3 className="m-0 text-sm font-semibold text-gray-900">{t('annotation.crossSlideSummary')}</h3>
          <span className="ml-auto text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
            {totalRegions} ROIs · {totalSlides} {t('annotation.slides')}
          </span>
          {showSummary ? <ChevronUp className="w-3.5 h-3.5 text-gray-400" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-400" />}
        </button>
        {showSummary && (
          <div className="p-3">
            {Object.keys(summary).length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">{t('annotation.noAnnotationsAcrossSlides')}</p>
            ) : (
              <div className="space-y-1.5">
                {Object.entries(summary).map(([label, data]) => (
                  <div key={label} className="flex items-center gap-2 px-2.5 py-1.5 bg-gray-50 rounded-lg">
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 border border-gray-200" style={{ backgroundColor: labelColors[label] }} />
                    <span className="flex-1 text-xs text-gray-700 truncate">{label}</span>
                    <span className="text-[10px] text-gray-500">{data.total} ROIs</span>
                    <span className="text-[10px] text-gray-400">{data.slides.size} {t('annotation.slides')}</span>
                  </div>
                ))}
              </div>
            )}
            {/* Create Dataset button */}
            {totalRegions > 0 && (
              <button
                onClick={onCreateDataset}
                className="mt-3 w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700 transition-colors shadow-sm"
              >
                <PackagePlus className="w-4 h-4" />
                {t('annotation.createDataset')}
              </button>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

