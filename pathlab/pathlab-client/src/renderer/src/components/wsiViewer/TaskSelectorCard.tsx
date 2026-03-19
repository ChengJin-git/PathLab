import { useTranslation } from 'react-i18next'
import { AvailableHeatmap, HeatmapData, PatchCAMData } from '../../api'
import { Card } from '../common'
import { Badge } from '../ui/badge'
import { Layers, ChevronDown, CheckCircle2, History, Trash2 } from 'lucide-react'
import { formatClasses } from './utils'

interface TaskSelectorCardProps {
  availableHeatmaps: AvailableHeatmap[]
  selectedTaskEntries: AvailableHeatmap[]
  selectedTaskId: string | undefined
  setSelectedTaskId: (id: string | undefined) => void
  selectedFoldKey: string | undefined
  setSelectedFoldKey: (key: string) => void
  availableFolds: string[]
  supportsFoldSelection: boolean
  uniqueTasks: (AvailableHeatmap & { isKFold?: boolean; numFolds?: number })[]
  isTaskDropdownOpen: boolean
  setIsTaskDropdownOpen: (open: boolean) => void
  setShowDeleteConfirm: (show: boolean) => void
  heatmapData: HeatmapData | null
  patchCAMData: PatchCAMData | null
  isPatchLevel: boolean
  wsiLabel?: string | null
  wsiEventStatus?: number | null
}

export function TaskSelectorCard({
  availableHeatmaps,
  selectedTaskEntries,
  selectedTaskId,
  setSelectedTaskId,
  selectedFoldKey,
  setSelectedFoldKey,
  availableFolds,
  supportsFoldSelection,
  uniqueTasks,
  isTaskDropdownOpen,
  setIsTaskDropdownOpen,
  setShowDeleteConfirm,
  heatmapData,
  patchCAMData,
  isPatchLevel,
  wsiLabel,
  wsiEventStatus,
}: TaskSelectorCardProps) {
  const { t } = useTranslation()
  const selectedTask = selectedTaskEntries.find(h => h.data_type === 'wsi' || h.data_type === 'patch')
    ?? selectedTaskEntries[0]
    ?? availableHeatmaps.find(h => h.task_id === selectedTaskId)
  const segmentationTask = selectedTaskEntries.find(
    h => h.task_type === 'segmentation' || h.task_type === 'patch_segmentation' || h.data_type === 'patch_segmentation'
  )
  const currentTaskType = heatmapData?.task_type
    ?? segmentationTask?.task_type
    ?? selectedTask?.task_type
    ?? (segmentationTask?.data_type === 'patch_segmentation' || selectedTask?.data_type === 'patch_segmentation'
      ? 'patch_segmentation'
      : undefined)
  const isSurvivalTask = currentTaskType === 'survival'
  const isSegmentationTask = !!segmentationTask || currentTaskType === 'segmentation' || currentTaskType === 'patch_segmentation'
  const displayPrediction = isPatchLevel ? (patchCAMData?.prediction ?? selectedTask?.prediction) : (heatmapData?.prediction ?? selectedTask?.prediction)
  const displayProbs = isPatchLevel ? (patchCAMData?.probs ?? selectedTask?.probs) : (heatmapData?.probs ?? selectedTask?.probs)
  const displayClasses = segmentationTask?.classes ?? selectedTask?.classes ?? patchCAMData?.classes ?? heatmapData?.classes ?? []

  return (
    <Card className="mb-4 overflow-visible shrink-0" noPadding>
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
        <Layers className="w-4 h-4 text-indigo-500" />
        <h3 className="m-0 text-sm font-semibold text-gray-900">{t('wsiViewerComponents.taskSelector.selectTask')}</h3>
        <span className="ml-auto text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
          {uniqueTasks.length} {t('wsiViewerComponents.taskSelector.available')}
        </span>
        <button
          onClick={() => setShowDeleteConfirm(true)}
          className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
          title={t('wsiViewerComponents.taskSelector.deleteAIResults')}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      <div className="p-3 relative">
        <div className="relative">
          <button
            onClick={() => setIsTaskDropdownOpen(!isTaskDropdownOpen)}
            className={`w-full flex items-center justify-between px-3 py-2.5 bg-white border rounded-lg shadow-sm transition-all duration-200 focus:outline-none focus:ring-4 focus:ring-indigo-500/10 active:scale-[0.99] group ${isTaskDropdownOpen ? 'border-indigo-500 ring-4 ring-indigo-500/10' : 'border-gray-200 hover:border-indigo-300 hover:shadow-md'
              }`}
          >
            <div className="flex flex-col items-start gap-1">
              <span className="text-gray-900 font-semibold text-sm tracking-tight text-left capitalize">
                {(() => {
                  const task = selectedTask;
                  if (!task) return t('wsiViewerComponents.taskSelector.selectATask');
                  return task.task_name || formatClasses(task.classes) || task.task_type?.replace(/_/g, ' ');
                })()}
              </span>
              {(() => {
                const task = selectedTask;
                if (task?.feature_extractor || task?.aggregator) {
                  return (
                    <div className="flex items-center gap-1">
                      {task.feature_extractor && (
                        <Badge variant="secondary" className="bg-purple-50 text-purple-700 hover:bg-purple-100 text-[10px] uppercase tracking-wider font-bold px-1.5 py-0">
                          {task.feature_extractor}
                        </Badge>
                      )}
                      {task.aggregator && task.data_type === 'wsi' && (
                        <Badge variant="secondary" className="bg-indigo-50 text-indigo-700 hover:bg-indigo-100 text-[10px] uppercase tracking-wider font-bold px-1.5 py-0">
                          {task.aggregator}
                        </Badge>
                      )}
                    </div>
                  );
                }
                return null;
              })()}
            </div>
            <ChevronDown
              className={`w-4 h-4 text-gray-400 transition-transform duration-300 ease-in-out group-hover:text-indigo-500 ${isTaskDropdownOpen ? 'rotate-180 text-indigo-500' : ''
                }`}
            />
          </button>

          {isTaskDropdownOpen && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setIsTaskDropdownOpen(false)}
              />
              <div className="absolute z-20 w-full mt-2 bg-white/90 backdrop-blur-xl border border-white/20 rounded-xl shadow-2xl shadow-indigo-500/10 overflow-hidden animate-in fade-in zoom-in-95 duration-200 origin-top ring-1 ring-black/5">
                <div className="max-h-[320px] overflow-y-auto py-2 scrollbar-thin scrollbar-thumb-gray-200">
                  {uniqueTasks.map(hm => (
                    <button
                      key={hm.task_id || hm.attention_file}
                      onClick={() => {
                        setSelectedTaskId(hm.task_id ?? undefined)
                        setIsTaskDropdownOpen(false)
                      }}
                      className="w-full text-left px-2 py-1 mx-2 rounded-lg transition-all duration-200 group/item flex items-center mb-1 last:mb-0 relative overflow-hidden max-w-[calc(100%-16px)]"
                    >
                      <div className={`absolute inset-0 transition-opacity duration-200 ${selectedTaskId === (hm.task_id || '')
                        ? 'bg-indigo-600 opacity-100'
                        : 'bg-gray-50 opacity-0 group-hover/item:opacity-100'
                        }`} />

                      <div className="relative z-10 w-full px-3 py-2.5 flex items-center justify-between">
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center gap-2">
                            <span className={`text-[13px] font-semibold tracking-tight transition-colors duration-200 capitalize ${selectedTaskId === (hm.task_id || '') ? 'text-white' : 'text-gray-700'
                              }`}>
                              {hm.task_name || formatClasses(hm.classes) || hm.task_type?.replace(/_/g, ' ')}
                            </span>
                            {hm.isKFold && (
                              <span className={`text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full transition-colors duration-200 ${selectedTaskId === (hm.task_id || '')
                                ? 'bg-white/20 text-white'
                                : 'bg-amber-50 text-amber-700'
                                }`}>
                                {hm.numFolds}-Fold
                              </span>
                            )}
                          </div>
                          {(hm.feature_extractor || (hm.aggregator && hm.data_type === 'wsi')) && (
                            <div className="flex items-center gap-1">
                              {hm.feature_extractor && (
                                <span className={`text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full w-fit transition-colors duration-200 ${selectedTaskId === (hm.task_id || '')
                                  ? 'bg-white/20 text-white'
                                  : 'bg-purple-50 text-purple-700'
                                  }`}>
                                  {hm.feature_extractor}
                                </span>
                              )}
                              {hm.aggregator && hm.data_type === 'wsi' && (
                                <span className={`text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full w-fit transition-colors duration-200 ${selectedTaskId === (hm.task_id || '')
                                  ? 'bg-white/20 text-white'
                                  : 'bg-indigo-50 text-indigo-700'
                                  }`}>
                                  {hm.aggregator}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                        {selectedTaskId === (hm.task_id || '') && (
                          <CheckCircle2 className="w-3.5 h-3.5 text-white" />
                        )}
                      </div>
                    </button>
                  ))}
                  {uniqueTasks.length === 0 && (
                    <div className="px-4 py-8 text-sm text-gray-500 text-center flex flex-col items-center gap-2">
                      <div className="w-8 h-8 rounded-full bg-gray-50 flex items-center justify-center">
                        <History className="w-4 h-4 text-gray-400" />
                      </div>
                      <p>{t('wsiViewerComponents.taskSelector.noTasksAvailable')}</p>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>

        {/* K-Fold Selector - show when multiple folds are available */}
        {supportsFoldSelection && availableFolds.length > 1 && (
          <div className="mt-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs text-gray-500 font-medium uppercase tracking-wider">{t('wsiViewerComponents.taskSelector.kFold')}</span>
              <span className="text-xs text-gray-400">({availableFolds.length} {t('wsiViewerComponents.taskSelector.folds')})</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {availableFolds.map((foldKey) => (
                <button
                  key={foldKey}
                  onClick={() => setSelectedFoldKey(foldKey)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-all duration-200 ${selectedFoldKey === foldKey
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                >
                  {foldKey.replace('_', ' ').replace('fold', 'Fold')}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Selected task info - supports heatmap, patch CAM, and segmentation mask tasks */}
        {(heatmapData || patchCAMData || (selectedTask && isSegmentationTask)) && (
          <div className={`mt-3 p-3 rounded-lg border ${isSurvivalTask
            ? 'bg-gradient-to-br from-emerald-50 to-teal-50 border-emerald-200'
            : isSegmentationTask
              ? 'bg-gradient-to-br from-violet-50 to-purple-50 border-violet-200'
              : 'bg-gradient-to-br from-indigo-50 to-blue-50 border-indigo-200'
            }`}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-semibold uppercase tracking-wider ${isSurvivalTask ? 'text-emerald-700' : isSegmentationTask ? 'text-violet-700' : 'text-indigo-700'
                  }`}>
                  {isSurvivalTask
                    ? t('wsiViewerComponents.taskSelector.riskGroup')
                    : isSegmentationTask
                      ? t('wsiViewerComponents.taskSelector.classes')
                      : t('wsiViewerComponents.taskSelector.prediction')}
                </span>
                {/* Show fold info for K-Fold trained models */}
                {supportsFoldSelection && heatmapData?.fold_key && (
                  <span className="text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700">
                    {heatmapData.fold_key.replace('_', ' ').replace('fold', 'Fold')}
                  </span>
                )}
              </div>
              {isPatchLevel ? (
                <Badge variant="secondary" className="bg-orange-50 text-orange-700 text-[10px]">
                  {isSegmentationTask
                    ? t('wsiViewerComponents.taskSelector.predictionMask')
                    : t('wsiViewerComponents.taskSelector.patchHeatmap')}
                </Badge>
              ) : (
                <span className="text-xs text-gray-500">{heatmapData?.num_patches?.toLocaleString()} {t('wsiViewerComponents.taskSelector.patches')}</span>
              )}
            </div>
            {/* Survival task: show risk group and risk score */}
            {isSurvivalTask ? (
              <>
                <div className={`text-lg font-bold ${heatmapData?.risk_group === 'High Risk' ? 'text-red-600' : 'text-emerald-600'
                  }`}>
                  {heatmapData?.risk_group || 'N/A'}
                </div>
                {heatmapData?.risk_score != null && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="text-xs bg-white/70 px-2 py-0.5 rounded border border-emerald-100">
                      {t('wsiViewerComponents.taskSelector.riskScore')}: {heatmapData.risk_score.toFixed(4)}
                    </span>
                  </div>
                )}
              </>
            ) : isSegmentationTask ? (
              <>
                <div className="text-lg font-bold text-violet-700">
                  {formatClasses(displayClasses, 99) || t('wsiViewerComponents.taskSelector.noClasses')}
                </div>
                {displayClasses.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {displayClasses.map((cls) => (
                      <span key={cls} className="text-xs bg-white/70 px-2 py-0.5 rounded border border-violet-100">
                        {cls}
                      </span>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <>
                {/* Classification task: show prediction and probabilities */}
                <div className="text-lg font-bold text-indigo-700">
                  {displayPrediction || 'N/A'}
                </div>
                {(() => {
                  const probs = displayProbs
                  if (probs && Object.keys(probs).length > 0) {
                    return (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(probs)
                          .sort(([, a], [, b]) => (b as number) - (a as number))
                          .slice(0, 3)
                          .map(([cls, prob]) => (
                            <span key={cls} className="text-xs bg-white/70 px-2 py-0.5 rounded border border-indigo-100">
                              {cls}: {((prob as number) * 100).toFixed(1)}%
                            </span>
                          ))}
                      </div>
                    )
                  }
                  return null
                })()}
                {(wsiLabel != null) && (
                  <div className="mt-2 pt-2 border-t border-indigo-100 flex items-center gap-1.5">
                    <span className="text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 shrink-0">GT</span>
                    <span className="text-xs font-medium text-indigo-700">{wsiLabel}</span>
                  </div>
                )}
              </>
            )}
            {isSurvivalTask && (wsiEventStatus != null) && (
              <div className="mt-2 pt-2 border-t border-emerald-100 flex items-center gap-1.5">
                <span className="text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 shrink-0">GT</span>
                <span className={`text-xs font-medium ${wsiEventStatus === 1 ? 'text-red-600' : 'text-emerald-600'}`}>
                  {wsiEventStatus === 1 ? t('wsiViewerComponents.taskSelector.event') : t('wsiViewerComponents.taskSelector.censored')}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

