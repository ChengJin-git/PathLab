import { useTranslation } from 'react-i18next'
import { Pencil, Square, Pentagon, Tag, ChevronDown, User, Users, UserPlus, Loader2 } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import { Tooltip } from '../ui/tooltip'

/** Preset label colors for auto-assignment */
export const LABEL_COLORS = [
  '#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4',
  '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#a855f7',
  '#6366f1', '#0ea5e9', '#84cc16', '#d946ef', '#f43f5e',
]

/** Get or assign a color for a label */
export function getColorForLabel(label: string, labelColors: Record<string, string>): string {
  if (labelColors[label]) return labelColors[label]
  const usedColors = new Set(Object.values(labelColors))
  const available = LABEL_COLORS.find(c => !usedColors.has(c))
  return available || LABEL_COLORS[Object.keys(labelColors).length % LABEL_COLORS.length]
}

interface AnnotationToolbarProps {
  annotationMode: boolean
  onToggleMode: () => void
  drawingTool: 'rect' | 'polygon'
  onToolChange: (tool: 'rect' | 'polygon') => void
  currentLabel: string
  onLabelChange: (label: string) => void
  labelColors: Record<string, string>
  allLabels: string[]
  onDropdownOpenChange?: (open: boolean) => void
  visibleLabels?: string[]
  missingCurrentLabel?: boolean
  onCreateCurrentLabelInMode?: () => void
  // Collaborative features
  editingMode?: 'personal' | 'shared'
  onToggleEditingMode?: () => void
  modeTransitioning?: boolean
  hasDatasetContext?: boolean
  isDatasetOwnerOrAdmin?: boolean
  onShareManage?: () => void
  sharedSaving?: boolean
}

export function AnnotationToolbar({
  annotationMode, onToggleMode,
  drawingTool, onToolChange,
  currentLabel, onLabelChange,
  labelColors, allLabels,
  onDropdownOpenChange,
  visibleLabels: _visibleLabels,
  missingCurrentLabel: _missingCurrentLabel,
  onCreateCurrentLabelInMode: _onCreateCurrentLabelInMode,
  editingMode = 'personal',
  onToggleEditingMode,
  modeTransitioning = false,
  hasDatasetContext,
  isDatasetOwnerOrAdmin,
  onShareManage,
  sharedSaving,
}: AnnotationToolbarProps) {
  const { t } = useTranslation()
  const [isLabelDropdownOpen, setIsLabelDropdownOpen] = useState(false)
  const [customLabel, setCustomLabel] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Notify parent when dropdown open state changes (so canvas can disable pointer-events)
  useEffect(() => {
    onDropdownOpenChange?.(isLabelDropdownOpen)
  }, [isLabelDropdownOpen, onDropdownOpenChange])

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsLabelDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const currentColor = labelColors[currentLabel] || '#3b82f6'
  const handleCustomLabelSubmit = () => {
    if (customLabel.trim()) {
      onLabelChange(customLabel.trim())
      setCustomLabel('')
      setIsLabelDropdownOpen(false)
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      {/* Annotation mode toggle */}
      <button
        type="button"
        onClick={onToggleMode}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
          annotationMode
            ? 'bg-indigo-600 text-white shadow-sm'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'
        }`}
      >
        <Pencil className="w-3.5 h-3.5" />
        {t('annotation.annotate')}
      </button>

      {annotationMode && (
        <>
          <div className="w-px h-5 bg-gray-200 mx-1" />

          {/* Mode Toggle - Only show if dataset context exists */}
          {hasDatasetContext && onToggleEditingMode && (
            <>
              <div className="flex items-center bg-gray-100 rounded-lg p-0.5 border border-gray-200">
                <Tooltip content={t('annotation.collab.personalDraft')}>
                <button
                  type="button"
                  onClick={editingMode !== 'personal' && !modeTransitioning ? onToggleEditingMode : undefined}
                  disabled={modeTransitioning && editingMode !== 'shared'}
                  className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-all ${
                    editingMode === 'personal'
                      ? 'bg-white shadow-sm text-indigo-600'
                      : modeTransitioning
                        ? 'text-gray-300 cursor-wait'
                        : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {modeTransitioning && editingMode === 'shared'
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    : <User className="w-3.5 h-3.5" />
                  }
                  <span>{t('annotation.collab.personalDraft')}</span>
                </button>
                </Tooltip>
                <Tooltip content={t('annotation.collab.collaborativeShare')}>
                <button
                  type="button"
                  onClick={editingMode !== 'shared' && !modeTransitioning ? onToggleEditingMode : undefined}
                  disabled={modeTransitioning && editingMode !== 'personal'}
                  className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-all ${
                    editingMode === 'shared'
                      ? 'bg-white shadow-sm text-indigo-600'
                      : modeTransitioning
                        ? 'text-gray-300 cursor-wait'
                        : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {modeTransitioning && editingMode === 'personal'
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    : <Users className="w-3.5 h-3.5" />
                  }
                  <span>{t('annotation.collab.collaborativeShare')}</span>
                </button>
                </Tooltip>
              </div>
              <div className="w-px h-5 bg-gray-200 mx-1" />
            </>
          )}

          {/* Drawing tool selection */}
          <div className="flex items-center bg-gray-100 rounded-lg p-0.5 border border-gray-200">
            <Tooltip content={t('annotation.rectangle')}>
            <button
              type="button"
              onClick={() => onToolChange('rect')}
              className={`p-1.5 rounded-md text-xs transition-all ${drawingTool === 'rect' ? 'bg-white shadow-sm text-indigo-600' : 'text-gray-500 hover:text-gray-700'}`}
            >
              <Square className="w-3.5 h-3.5" />
            </button>
            </Tooltip>
            <Tooltip content={t('annotation.polygon')}>
            <button
              type="button"
              onClick={() => onToolChange('polygon')}
              className={`p-1.5 rounded-md text-xs transition-all ${drawingTool === 'polygon' ? 'bg-white shadow-sm text-indigo-600' : 'text-gray-500 hover:text-gray-700'}`}
            >
              <Pentagon className="w-3.5 h-3.5" />
            </button>
            </Tooltip>
          </div>

          <div className="w-px h-5 bg-gray-200 mx-1" />

          <div className="flex items-center">
            <div className="relative" ref={dropdownRef}>
              <button
                type="button"
                onClick={() => setIsLabelDropdownOpen(!isLabelDropdownOpen)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all bg-gray-100 border border-gray-200 text-gray-700 hover:bg-gray-200"
              >
                <span className="w-2.5 h-2.5 rounded-full border border-gray-300 flex-shrink-0" style={{ backgroundColor: currentColor }} />
                <span className="max-w-[80px] truncate">{currentLabel || t('annotation.defaultLabel')}</span>
                <ChevronDown className="w-3 h-3 text-gray-400" />
              </button>

              {isLabelDropdownOpen && (
                <div className="absolute top-full mt-1 left-0 bg-white border border-gray-200 rounded-xl shadow-xl z-50 w-52 py-1.5 overflow-hidden">
                  {allLabels.map(label => (
                    <button
                      type="button"
                      key={label}
                      onClick={() => { onLabelChange(label); setIsLabelDropdownOpen(false) }}
                      className={`w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-gray-50 transition-colors ${label === currentLabel ? 'bg-indigo-50 text-indigo-700' : 'text-gray-700'}`}
                    >
                      <span className="w-2.5 h-2.5 rounded-full border border-gray-200 flex-shrink-0" style={{ backgroundColor: labelColors[label] }} />
                      <span className="truncate">{label}</span>
                    </button>
                  ))}
                  {allLabels.length > 0 && <div className="border-t border-gray-100 mx-2 my-1" />}
                  <div className="px-2.5 py-2">
                    <div className="flex items-center gap-1.5">
                      <input
                        type="text"
                        value={customLabel}
                        onChange={e => setCustomLabel(e.target.value)}
                        placeholder={t('annotation.newLabel')}
                        className="flex-1 px-2.5 py-1.5 text-xs border border-gray-200 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                        onKeyDown={e => { if (e.key === 'Enter') handleCustomLabelSubmit() }}
                        autoFocus
                      />
                      <button
                        type="button"
                        onClick={handleCustomLabelSubmit}
                        className="p-1.5 text-indigo-600 hover:bg-indigo-50 rounded-lg disabled:opacity-30 transition-colors"
                        disabled={!customLabel.trim()}
                      >
                        <Tag className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Shared Mode Actions - Only visible in shared mode */}
          {editingMode === 'shared' && (
            <>
              {/* Only Owner/Admin actions */}
              {isDatasetOwnerOrAdmin && (
                <>
                  <div className="w-px h-5 bg-gray-200 mx-1" />
                  <div className="flex items-center gap-1">
                    {onShareManage && (
                      <Tooltip content={t('annotation.collab.manageCollaborators')}>
                      <button
                        type="button"
                        onClick={onShareManage}
                        className="p-1.5 text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                      >
                        <UserPlus className="w-3.5 h-3.5" />
                      </button>
                      </Tooltip>
                    )}

                  </div>
                </>
              )}
              
              {/* Shared Saving Indicator */}
              {sharedSaving && (
                <>
                  <div className="w-px h-5 bg-gray-200 mx-1" />
                  <Loader2 className="w-3 h-3 animate-spin text-indigo-500" />
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
