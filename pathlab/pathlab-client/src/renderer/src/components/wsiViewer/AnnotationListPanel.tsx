import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Trash2, PackagePlus, ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react'
import { AnnotationRegion, AnnotationsMap, DatasetAnnotationSummaryResponse } from '../../api/annotation'
import { Card } from '../common'

interface AnnotationListPanelProps {
  currentWsiId: string
  regions: AnnotationRegion[]
  allAnnotations: AnnotationsMap
  preferRemoteCrossSlideSummary?: boolean
  crossSlideSummary?: DatasetAnnotationSummaryResponse | null
  loadingCrossSlideSummary?: boolean
  labelColors: Record<string, string>
  focusedRegionId?: string | null
  onFocusRegion?: (regionId: string) => void
  onUpdateRegion: (regionId: string, updates: Partial<AnnotationRegion>) => void
  onDeleteRegion: (regionId: string) => void
  onDeleteRegions: (regionIds: string[]) => void
  onDeleteCrossSlideByLabel: (labels: string[]) => void | Promise<void>
  onCreateDataset: () => void
}

export function AnnotationListPanel({
  currentWsiId,
  regions,
  allAnnotations,
  preferRemoteCrossSlideSummary = false,
  crossSlideSummary,
  loadingCrossSlideSummary = false,
  labelColors,
  focusedRegionId = null,
  onFocusRegion,
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
  // Confirmation dialog state: { type, message } or null
  const [deleteConfirm, setDeleteConfirm] = useState<{ type: 'current' | 'crossSlide'; message: string } | null>(null)

  const localSummary = useMemo(() => {
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

  const isRemoteSummaryPending = preferRemoteCrossSlideSummary && (!crossSlideSummary || loadingCrossSlideSummary)

  const effectiveSummary = useMemo(() => {
    if (preferRemoteCrossSlideSummary && !crossSlideSummary) {
      return {
        counts: {},
        totalRegions: 0,
        totalSlides: 0,
      }
    }

    if (!crossSlideSummary) {
      return {
        counts: localSummary,
        totalRegions: Object.values(allAnnotations).reduce((sum, regs) => sum + regs.length, 0),
        totalSlides: Object.keys(allAnnotations).filter(k => allAnnotations[k].length > 0).length,
      }
    }

    return {
      counts: Object.fromEntries(
        Object.entries(crossSlideSummary.labels).map(([label, data]) => [
          label,
          { total: data.total_regions, slides: new Set<string>(Array.from({ length: data.total_slides }, (_, idx) => `${label}:${idx}`)) },
        ])
      ) as Record<string, { total: number; slides: Set<string> }>,
      totalRegions: crossSlideSummary.total_regions,
      totalSlides: crossSlideSummary.total_slides,
    }
  }, [allAnnotations, crossSlideSummary, localSummary, preferRemoteCrossSlideSummary])

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
    setDeleteConfirm({
      type: 'current',
      message: t('annotation.confirmDeleteSelected', { count: selectedRegionIds.size }),
    })
  }

  const toggleSelectCrossSlideLabel = (label: string) => {
    setSelectedCrossSlideLabels(prev => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  const allCrossSlideLabelsSelected = Object.keys(effectiveSummary.counts).length > 0 && Object.keys(effectiveSummary.counts).every(l => selectedCrossSlideLabels.has(l))

  const toggleSelectAllCrossSlideLabels = () => {
    if (allCrossSlideLabelsSelected) {
      setSelectedCrossSlideLabels(new Set())
    } else {
      setSelectedCrossSlideLabels(new Set(Object.keys(effectiveSummary.counts)))
    }
  }

  const selectedCrossSlideCount = useMemo(() => {
    let total = 0
    const slides = new Set<string>()
    for (const label of selectedCrossSlideLabels) {
      if (effectiveSummary.counts[label]) {
        total += effectiveSummary.counts[label].total
        effectiveSummary.counts[label].slides.forEach(s => slides.add(s))
      }
    }
    return { total, slides: slides.size }
  }, [effectiveSummary.counts, selectedCrossSlideLabels])

  const handleBatchDeleteCrossSlide = () => {
    if (selectedCrossSlideLabels.size === 0) return
    setDeleteConfirm({
      type: 'crossSlide',
      message: t('annotation.confirmDeleteByLabel', { count: selectedCrossSlideCount.total, slides: selectedCrossSlideCount.slides }),
    })
  }

  const handleConfirmDelete = () => {
    if (!deleteConfirm) return
    if (deleteConfirm.type === 'current') {
      onDeleteRegions(Array.from(selectedRegionIds))
      setSelectedRegionIds(new Set())
    } else {
      onDeleteCrossSlideByLabel(Array.from(selectedCrossSlideLabels))
      setSelectedCrossSlideLabels(new Set())
    }
    setDeleteConfirm(null)
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
          <div className="ml-auto flex items-center gap-2">
            {someCurrentSelected && (
              <button
                onClick={handleBatchDeleteCurrent}
                className="flex items-center gap-1 px-2 py-0.5 text-red-500 hover:text-red-600 text-xs transition-colors"
                title={t('annotation.deleteSelected', { count: selectedRegionIds.size })}
              >
                <Trash2 className="w-3 h-3" />
                <span>{selectedRegionIds.size}</span>
              </button>
            )}
            <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
              {regions.length} {t('annotation.regions')}
            </span>
          </div>
        </div>
        <div className="p-3 max-h-[300px] overflow-y-auto">
          {regions.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-6">{t('annotation.noAnnotations')}</p>
          ) : (
            <div className="space-y-1.5">
              {regions.map((region, idx) => (
                <div
                  key={region.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onFocusRegion?.(region.id)}
                  onKeyDown={e => {
                    if (e.target !== e.currentTarget) return
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onFocusRegion?.(region.id)
                    }
                  }}
                  className={`flex items-center gap-2 px-2.5 py-2 rounded-lg group transition-all cursor-pointer ${focusedRegionId === region.id ? 'bg-amber-50 ring-2 ring-amber-300 shadow-sm' : selectedRegionIds.has(region.id) ? 'bg-indigo-50 ring-1 ring-indigo-200' : 'bg-gray-50 hover:bg-gray-100'}`}
                >
                  <input
                    type="checkbox"
                    checked={selectedRegionIds.has(region.id)}
                    onChange={() => toggleSelectRegion(region.id)}
                    onClick={e => e.stopPropagation()}
                    className="w-3.5 h-3.5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer flex-shrink-0"
                  />
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 border border-gray-200" style={{ backgroundColor: labelColors[region.label] || region.color }} />
                  {editingId === region.id ? (
                    <input
                      type="text"
                      value={editLabel}
                      onChange={e => setEditLabel(e.target.value)}
                      onClick={e => e.stopPropagation()}
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
                  <button onClick={e => { e.stopPropagation(); handleStartEdit(region) }} className="p-1 text-gray-400 hover:text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity" title={t('annotation.editLabel')}>
                    <Pencil className="w-3 h-3" />
                  </button>
                  <button onClick={e => { e.stopPropagation(); onDeleteRegion(region.id) }} className="p-1 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity" title={t('annotation.deleteRegion')}>
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
          className="flex items-start gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white w-full text-left"
        >
          {!isRemoteSummaryPending && Object.keys(effectiveSummary.counts).length > 0 && (
            <input
              type="checkbox"
              checked={allCrossSlideLabelsSelected}
              onChange={(e) => { e.stopPropagation(); toggleSelectAllCrossSlideLabels() }}
              onClick={(e) => e.stopPropagation()}
              className="mt-0.5 w-3.5 h-3.5 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer flex-shrink-0"
              title={allCrossSlideLabelsSelected ? t('annotation.deselectAll') : t('annotation.selectAll')}
            />
          )}
          <PackagePlus className="mt-0.5 w-4 h-4 text-emerald-500 flex-shrink-0" />
          <div className="min-w-0 flex flex-1 flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="m-0 min-w-0 flex-1 text-sm font-semibold text-gray-900 break-words">{t('annotation.crossSlideSummary')}</h3>
            {selectedCrossSlideLabels.size > 0 && (
              <span
                onClick={(e) => { e.stopPropagation(); handleBatchDeleteCrossSlide() }}
                className="flex items-center gap-1 px-2 py-0.5 text-red-500 hover:text-red-600 text-xs transition-colors cursor-pointer flex-shrink-0"
                title={t('annotation.deleteSelected', { count: selectedCrossSlideCount.total })}
              >
                <Trash2 className="w-3 h-3" />
                <span>{selectedCrossSlideCount.total}</span>
              </span>
            )}
            <span className="max-w-full text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded leading-5 break-words">
              {isRemoteSummaryPending
                ? t('common.loading')
                : `${effectiveSummary.totalRegions} ROIs · ${effectiveSummary.totalSlides} ${t('annotation.slides')}`}
            </span>
          </div>
          {showSummary ? <ChevronUp className="mt-0.5 w-3.5 h-3.5 text-gray-400 flex-shrink-0" /> : <ChevronDown className="mt-0.5 w-3.5 h-3.5 text-gray-400 flex-shrink-0" />}
        </button>
        {showSummary && (
          <div className="p-3">
            {isRemoteSummaryPending ? (
              <p className="text-xs text-gray-400 text-center py-4">{t('common.loading')}</p>
            ) : Object.keys(effectiveSummary.counts).length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">{t('annotation.noAnnotationsAcrossSlides')}</p>
            ) : (
              <div className="space-y-1.5">
                {Object.entries(effectiveSummary.counts).map(([label, data]) => (
                  <div key={label} className={`flex flex-wrap items-center gap-x-2 gap-y-1 px-2.5 py-1.5 rounded-lg transition-colors ${selectedCrossSlideLabels.has(label) ? 'bg-emerald-50 ring-1 ring-emerald-200' : 'bg-gray-50'}`}>
                    <input
                      type="checkbox"
                      checked={selectedCrossSlideLabels.has(label)}
                      onChange={() => toggleSelectCrossSlideLabel(label)}
                      className="w-3.5 h-3.5 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer flex-shrink-0"
                    />
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 border border-gray-200" style={{ backgroundColor: labelColors[label] || crossSlideSummary?.labels[label]?.color || '#3b82f6' }} />
                    <span className="min-w-0 flex-1 text-xs text-gray-700 break-words">{label}</span>
                    <div className="ml-auto flex items-center gap-2 text-[10px] leading-4 text-gray-500">
                      <span>{data.total} ROIs</span>
                      <span className="text-gray-400">{data.slides.size} {t('annotation.slides')}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {/* Create Dataset button */}
            {effectiveSummary.totalRegions > 0 && !isRemoteSummaryPending && (
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

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center gap-3 px-6 pt-6 pb-2">
              <div className="p-2 bg-red-100 rounded-full">
                <AlertTriangle className="w-5 h-5 text-red-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('common.delete')}</h3>
            </div>
            <p className="px-6 py-3 text-sm text-gray-600 leading-relaxed">
              {deleteConfirm.message}
            </p>
            <div className="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 border-t border-gray-100">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleConfirmDelete}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors flex items-center gap-1.5"
              >
                <Trash2 className="w-3.5 h-3.5" />
                {t('common.delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

