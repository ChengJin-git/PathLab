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
  onDeleteRegions: (regionIds: string[]) => void
  onDeleteCrossSlideByLabel: (labels: string[]) => void
  onCreateDataset: () => void
}

export function AnnotationListPanel({
  currentWsiId,
  regions,
  allAnnotations,
  labelColors,
  onUpdateRegion,
  onDeleteRegion,
  onDeleteRegions,
  onDeleteCrossSlideByLabel,
  onCreateDataset,
}: AnnotationListPanelProps) {
  const { t } = useTranslation()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [showSummary, setShowSummary] = useState(true)
  const [selectedRegionIds, setSelectedRegionIds] = useState<Set<string>>(new Set())
  const [selectedCrossSlideLabels, setSelectedCrossSlideLabels] = useState<Set<string>>(new Set())

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

  const allCurrentSelected = regions.length > 0 && regions.every(r => selectedRegionIds.has(r.id))
  const someCurrentSelected = selectedRegionIds.size > 0

  const toggleSelectRegion = (id: string) => {
    setSelectedRegionIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAllCurrent = () => {
    if (allCurrentSelected) {
      setSelectedRegionIds(new Set())
    } else {
      setSelectedRegionIds(new Set(regions.map(r => r.id)))
    }
  }

  const handleBatchDeleteCurrent = () => {
    if (selectedRegionIds.size === 0) return
    if (confirm(t('annotation.confirmDeleteSelected', { count: selectedRegionIds.size }))) {
      onDeleteRegions(Array.from(selectedRegionIds))
      setSelectedRegionIds(new Set())
    }
  }

  const toggleSelectCrossSlideLabel = (label: string) => {
    setSelectedCrossSlideLabels(prev => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  const allCrossSlideLabelsSelected = Object.keys(summary).length > 0 && Object.keys(summary).every(l => selectedCrossSlideLabels.has(l))

  const toggleSelectAllCrossSlideLabels = () => {
    if (allCrossSlideLabelsSelected) {
      setSelectedCrossSlideLabels(new Set())
    } else {
      setSelectedCrossSlideLabels(new Set(Object.keys(summary)))
    }
  }

  const selectedCrossSlideCount = useMemo(() => {
    let total = 0
    const slides = new Set<string>()
    for (const label of selectedCrossSlideLabels) {
      if (summary[label]) {
        total += summary[label].total
        summary[label].slides.forEach(s => slides.add(s))
      }
    }
    return { total, slides: slides.size }
  }, [selectedCrossSlideLabels, summary])

  const handleBatchDeleteCrossSlide = () => {
    if (selectedCrossSlideLabels.size === 0) return
    if (confirm(t('annotation.confirmDeleteByLabel', { count: selectedCrossSlideCount.total, slides: selectedCrossSlideCount.slides }))) {
      onDeleteCrossSlideByLabel(Array.from(selectedCrossSlideLabels))
      setSelectedCrossSlideLabels(new Set())
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Current slide annotations */}
      <Card className="overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
          {regions.length > 0 && (
            <input
              type="checkbox"
              checked={allCurrentSelected}
              onChange={toggleSelectAllCurrent}
              className="w-3.5 h-3.5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
              title={allCurrentSelected ? t('annotation.deselectAll') : t('annotation.selectAll')}
            />
          )}
          <Pencil className="w-4 h-4 text-indigo-500" />
          <h3 className="m-0 text-sm font-semibold text-gray-900">{t('annotation.currentSlide')}</h3>
          <span className="ml-auto text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
            {regions.length} {t('annotation.regions')}
          </span>
        </div>
        {/* Batch delete bar for current slide */}
        {someCurrentSelected && (
          <div className="flex items-center gap-2 px-4 py-2 bg-red-50 border-b border-red-100">
            <button
              onClick={handleBatchDeleteCurrent}
              className="flex items-center gap-1.5 px-3 py-1 bg-red-500 text-white text-xs font-medium rounded-md hover:bg-red-600 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
              {t('annotation.deleteSelected', { count: selectedRegionIds.size })}
            </button>
            <button
              onClick={() => setSelectedRegionIds(new Set())}
              className="text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              {t('annotation.deselectAll')}
            </button>
          </div>
        )}
        <div className="p-3 max-h-[300px] overflow-y-auto">
          {regions.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-6">{t('annotation.noAnnotations')}</p>
          ) : (
            <div className="space-y-1.5">
              {regions.map((region, idx) => (
                <div key={region.id} className={`flex items-center gap-2 px-2.5 py-2 rounded-lg group transition-colors ${selectedRegionIds.has(region.id) ? 'bg-indigo-50 ring-1 ring-indigo-200' : 'bg-gray-50 hover:bg-gray-100'}`}>
                  <input
                    type="checkbox"
                    checked={selectedRegionIds.has(region.id)}
                    onChange={() => toggleSelectRegion(region.id)}
                    className="w-3.5 h-3.5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer flex-shrink-0"
                  />
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
          {Object.keys(summary).length > 0 && (
            <input
              type="checkbox"
              checked={allCrossSlideLabelsSelected}
              onChange={(e) => { e.stopPropagation(); toggleSelectAllCrossSlideLabels() }}
              onClick={(e) => e.stopPropagation()}
              className="w-3.5 h-3.5 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer"
              title={allCrossSlideLabelsSelected ? t('annotation.deselectAll') : t('annotation.selectAll')}
            />
          )}
          <PackagePlus className="w-4 h-4 text-emerald-500" />
          <h3 className="m-0 text-sm font-semibold text-gray-900">{t('annotation.crossSlideSummary')}</h3>
          <span className="ml-auto text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
            {totalRegions} ROIs · {totalSlides} {t('annotation.slides')}
          </span>
          {showSummary ? <ChevronUp className="w-3.5 h-3.5 text-gray-400" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-400" />}
        </button>
        {/* Batch delete bar for cross-slide */}
        {selectedCrossSlideLabels.size > 0 && (
          <div className="flex items-center gap-2 px-4 py-2 bg-red-50 border-b border-red-100">
            <button
              onClick={handleBatchDeleteCrossSlide}
              className="flex items-center gap-1.5 px-3 py-1 bg-red-500 text-white text-xs font-medium rounded-md hover:bg-red-600 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
              {t('annotation.deleteSelected', { count: selectedCrossSlideCount.total })}
            </button>
            <button
              onClick={() => setSelectedCrossSlideLabels(new Set())}
              className="text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              {t('annotation.deselectAll')}
            </button>
          </div>
        )}
        {showSummary && (
          <div className="p-3">
            {Object.keys(summary).length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">{t('annotation.noAnnotationsAcrossSlides')}</p>
            ) : (
              <div className="space-y-1.5">
                {Object.entries(summary).map(([label, data]) => (
                  <div key={label} className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-colors ${selectedCrossSlideLabels.has(label) ? 'bg-emerald-50 ring-1 ring-emerald-200' : 'bg-gray-50'}`}>
                    <input
                      type="checkbox"
                      checked={selectedCrossSlideLabels.has(label)}
                      onChange={() => toggleSelectCrossSlideLabel(label)}
                      className="w-3.5 h-3.5 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer flex-shrink-0"
                    />
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

