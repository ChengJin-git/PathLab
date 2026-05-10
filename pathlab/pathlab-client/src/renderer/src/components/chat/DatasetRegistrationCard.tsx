import React, { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  UploadCloud, FolderPlus, File as FileIcon, CheckCircle,
  Loader2, Database, AlertTriangle, Download,
  ThumbsUp, ThumbsDown
} from 'lucide-react'
import { fetchDatasets, DatasetSummary, downloadCSVTemplate } from '../../api'
import { useBackgroundTask, UploadTaskFile } from '../../contexts/BackgroundTaskContext'
import { getSegmentationStem, mergeSegmentationJsonFiles, summarizeSegmentationMatches } from '../../lib/segmentationUploadUtils'
import { Select } from '../ui/select'
import { organSources, organSourceKeyMap } from '../../constants/wsi'
import { getTaskFamily, resolveUploadTaskType, toCanonicalTaskType, type UploadTaskMode, type TaskType } from '../../constants/training'
import { collectItemsFromDataTransfer, type CollectionProgressSnapshot, type LocalItem } from '../upload'

export function parseDatasetRegistrationConfig(content: string): DatasetRegistrationConfig | null {
  const match = content.match(/\[DATASET_REGISTRATION\]([\s\S]*?)\[\/DATASET_REGISTRATION\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1].trim())
  } catch {
    return null
  }
}

export function removeDatasetRegistrationBlock(content: string): string {
  return content.replace(/\[DATASET_REGISTRATION\][\s\S]*?\[\/DATASET_REGISTRATION\]/g, '').trim()
}

interface DatasetRegistrationConfig {
  dataset_id?: string
  dataset_name?: string
  source_organ?: string
  upload_mode?: UploadTaskMode
  aggregation_level?: 'file' | 'case'
  initial_view?: 'new' | 'existing'
  submitted_task_id?: string
  submitted_file_count?: number
  submitted_dataset_name?: string
  submitted_mode?: 'existing' | 'new'
  is_public?: boolean
}

export interface DatasetRegistrationCardProps {
  config?: DatasetRegistrationConfig
  onUploadStarted?: (taskId: string, fileCount: number, datasetName: string, mode: 'existing' | 'new') => void
  onError?: (error: string) => void
  messageId?: string
  onHelpfulnessFeedback?: (
    messageId: string,
    helpfulness: 'helpful' | 'not_helpful',
    relatedTaskId: string,
    taskType?: 'training' | 'inference' | 'analysis' | 'registration',
    taskTitle?: string
  ) => void
  savedHelpfulnessFeedback?: 'helpful' | 'not_helpful' | null
}

export function DatasetRegistrationCard({ 
  config, 
  onUploadStarted, 
  onError,
  messageId,
  onHelpfulnessFeedback,
  savedHelpfulnessFeedback
}: DatasetRegistrationCardProps) {
  const { t } = useTranslation()
  const { addUploadTask } = useBackgroundTask()
  
  const [mode, setMode] = useState<'existing' | 'new'>(
    config?.initial_view ? config.initial_view : (config?.dataset_id ? 'existing' : 'new')
  )
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(config?.dataset_id || '')
  const [newDatasetName, setNewDatasetName] = useState(config?.dataset_name || '')
  const [datasetSourceSelection, setDatasetSourceSelection] = useState<string>(config?.source_organ || '')
  const [datasetSourceCustom, setDatasetSourceCustom] = useState('')
  const [isPublic, setIsPublic] = useState<boolean>(Boolean(config?.is_public))
  const canonicalUploadMode = resolveUploadTaskType(config?.upload_mode ?? 'classification')
  const isSegmentation = getTaskFamily(canonicalUploadMode) === 'segmentation'
  const [dataLevel, setDataLevel] = useState<'file' | 'case'>(isSegmentation ? 'file' : (config?.aggregation_level || 'file'))
  
  const [helpfulnessFeedback, setHelpfulnessFeedback] = useState<'helpful' | 'not_helpful' | null>(savedHelpfulnessFeedback || null)
  const [submittedTaskId, setSubmittedTaskId] = useState<string>(config?.submitted_task_id || '')

  const [localItems, setLocalItems] = useState<LocalItem[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [collectionProgress, setCollectionProgress] = useState<CollectionProgressSnapshot | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'success' | 'error'>(
    config?.submitted_task_id ? 'success' : 'idle'
  )
  
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [segMissingMasks, setSegMissingMasks] = useState(false)
  const [segmentationJsonFiles, setSegmentationJsonFiles] = useState<Map<string, File>>(new Map())
  const [segmentationDuplicateJsonStems, setSegmentationDuplicateJsonStems] = useState<Set<string>>(new Set())
  const isCollecting = collectionProgress !== null && !collectionProgress.completed
  const segmentationJsonOnlyAppend = isSegmentation && mode === 'existing' && localItems.length === 0 && segmentationJsonFiles.size > 0
  const readyUploadCount = segmentationJsonOnlyAppend ? segmentationJsonFiles.size : localItems.length

  const filteredDatasets = useMemo(() => {
    return datasets.filter(dataset => {
      if (isSegmentation) {
        return getTaskFamily(dataset.task_type) === 'segmentation' && dataset.data_type === 'patch' && dataset.aggregation_level === 'file'
      }
      if (!config?.upload_mode) return true
      return getTaskFamily(dataset.task_type) === getTaskFamily(canonicalUploadMode)
    })
  }, [datasets, isSegmentation, config?.upload_mode, canonicalUploadMode])

  const selectedDataset = useMemo(
    () => datasets.find(dataset => dataset.dataset_id === selectedDatasetId),
    [datasets, selectedDatasetId]
  )

  const isOtherSource = datasetSourceSelection === 'Other'

  const getResolvedDatasetSource = () => {
    if (isOtherSource) return datasetSourceCustom.trim()
    return datasetSourceSelection.trim()
  }

  const getDatasetSource = (dataset?: DatasetSummary | null) => {
    const source = dataset?.source_organ?.trim()
    return source || t('chatComponents.datasetRegistration.unknownSource')
  }

  useEffect(() => {
    if (config?.submitted_task_id) {
      setUploadStatus('success')
      setSubmittedTaskId(config.submitted_task_id)
    }
  }, [config?.submitted_task_id])

  useEffect(() => {
    if (savedHelpfulnessFeedback) {
      setHelpfulnessFeedback(savedHelpfulnessFeedback)
    }
  }, [savedHelpfulnessFeedback])

  useEffect(() => {
    loadDatasets()
  }, [])

  useEffect(() => {
    if (isSegmentation) {
      setDataLevel('file')
    }
  }, [isSegmentation])

  useEffect(() => {
    if (mode === 'existing' && selectedDatasetId && !filteredDatasets.some(d => d.dataset_id === selectedDatasetId)) {
      setSelectedDatasetId('')
    }
  }, [mode, selectedDatasetId, filteredDatasets])

  useEffect(() => {
    if (!isSegmentation) {
      setSegMissingMasks(false)
      return
    }

    const { duplicateImageStems } = summarizeSegmentationMatches(localItems, segmentationJsonFiles)
    setSegMissingMasks(
      duplicateImageStems.length > 0 ||
      (mode === 'new' && localItems.length === 0 && segmentationJsonFiles.size > 0) ||
      segmentationDuplicateJsonStems.size > 0
    )
  }, [isSegmentation, localItems, mode, segmentationJsonFiles, segmentationDuplicateJsonStems])

  useEffect(() => {
    const configuredSource = config?.source_organ?.trim()
    if (!configuredSource) return

    if (organSources.includes(configuredSource)) {
      setDatasetSourceSelection(configuredSource)
      setDatasetSourceCustom('')
      return
    }

    setDatasetSourceSelection('Other')
    setDatasetSourceCustom(configuredSource)
  }, [config?.source_organ])

  const loadDatasets = async () => {
    try {
      setLoadingDatasets(true)
      const data = await fetchDatasets()
      setDatasets(data.items)
    } catch (err) {
      console.error('Failed to load datasets', err)
    } finally {
      setLoadingDatasets(false)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      let uploadMode: TaskType = canonicalUploadMode

      if (mode === 'existing' && selectedDatasetId) {
        const dataset = datasets.find(d => d.dataset_id === selectedDatasetId)
        if (dataset && dataset.task_type) {
          uploadMode = toCanonicalTaskType(dataset.task_type, dataset.data_type) || resolveUploadTaskType(config?.upload_mode ?? 'classification', { dataType: dataset.data_type })
        }
      } else {
        uploadMode = canonicalUploadMode
      }

      await downloadCSVTemplate(uploadMode)
    } catch (err) {
      console.error('Failed to download template', err)
      if (onError) onError(t('chatComponents.datasetRegistration.downloadTemplateFailed'))
    }
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    setValidationErrors([])

    try {
      const dataItems = Array.from(e.dataTransfer.items || [])
      const hasEntries = dataItems.some(item => (item as any).webkitGetAsEntry)

      if (!hasEntries && dataItems.length > 0 && (e.dataTransfer.files?.length ?? 0) === 0) {
        setValidationErrors([t('chatComponents.datasetRegistration.browserNotSupported')])
        return
      }

      setCollectionProgress({
        phase: 'preparing',
        totalTopLevelEntries: 0,
        processedItems: 0,
        discoveredFiles: 0,
        discoveredDirectories: 0,
        completed: false,
      })

      const result = await collectItemsFromDataTransfer(e.dataTransfer, {
        onProgress: setCollectionProgress,
      })

      const validItems = result.items
      const jsonFiles = isSegmentation ? result.jsonFiles : []

      if (validItems.length === 0 && !(isSegmentation && mode === 'existing' && jsonFiles.length > 0)) {
        setCollectionProgress(null)
        setValidationErrors([t('chatComponents.datasetRegistration.noValidImages')])
        return
      }

      setLocalItems(prev => {
        const merged = new Map(prev.map(item => [item.key, item]))
        validItems.forEach(item => merged.set(item.key, item))
        return Array.from(merged.values())
      })

      if (isSegmentation) {
        let duplicateJsonStems: string[] = []
        setSegmentationJsonFiles(prev => {
          const merged = mergeSegmentationJsonFiles(prev, jsonFiles)
          duplicateJsonStems = merged.duplicateJsonStems
          return merged.jsonFilesByStem
        })
        if (duplicateJsonStems.length > 0) {
          setSegmentationDuplicateJsonStems(prev => new Set([...prev, ...duplicateJsonStems]))
        }
      }

      setCollectionProgress(null)

    } catch (error) {
      setCollectionProgress(null)
      console.error('File processing error:', error)
      setValidationErrors([t('chatComponents.datasetRegistration.fileProcessingError')])
    }
  }

  const clearSelection = () => {
    setLocalItems([])
    setCollectionProgress(null)
    setSegmentationJsonFiles(new Map())
    setSegmentationDuplicateJsonStems(new Set())
    setValidationErrors([])
  }

  const handleStartUpload = async () => {
    if (readyUploadCount === 0) return
    setIsUploading(true)
    setValidationErrors([])

    try {
      if (mode === 'new' && !newDatasetName.trim()) {
        throw new Error(t('chatComponents.datasetRegistration.enterDatasetName'))
      }
      if (mode === 'existing' && !selectedDatasetId) {
        throw new Error(t('chatComponents.datasetRegistration.selectDataset'))
      }

      if (mode === 'existing' && !filteredDatasets.some(d => d.dataset_id === selectedDatasetId)) {
        throw new Error('Selected dataset is not compatible with this registration mode.')
      }

      if (isSegmentation) {
        const { duplicateImageStems } = summarizeSegmentationMatches(localItems, segmentationJsonFiles)
        if (segmentationDuplicateJsonStems.size > 0) {
          throw new Error(`Duplicate segmentation JSON stems detected: ${Array.from(segmentationDuplicateJsonStems).join(', ')}`)
        }
        if (duplicateImageStems.length > 0) {
          throw new Error(`Duplicate segmentation image stems detected: ${duplicateImageStems.join(', ')}`)
        }
        if (mode === 'new' && localItems.length === 0) {
          throw new Error('Segmentation registration requires at least one image file for a new dataset.')
        }
      }

      const uploadTasks: UploadTaskFile[] = segmentationJsonOnlyAppend
        ? Array.from(segmentationJsonFiles.values()).map(file => ({
          key: `seg-json-${file.name}-${file.size}`,
          name: file.name,
          file,
          metadata: {
            dataset_id: selectedDatasetId,
            task_type: resolveUploadTaskType(canonicalUploadMode, { fileName: file.name, fileSize: file.size, dataType: 'patch' }),
          }
        }))
        : localItems.map(item => {
          const resolvedDatasetSource = getResolvedDatasetSource()
          const matchedSegmentationJson = isSegmentation
            ? segmentationJsonFiles.get(getSegmentationStem(item.name))
            : undefined
          const selectedDataType = mode === 'existing'
            ? datasets.find(d => d.dataset_id === selectedDatasetId)?.data_type
            : undefined
          const taskType = resolveUploadTaskType(canonicalUploadMode, {
            fileName: item.name,
            fileSize: item.file?.size ?? null,
            dataType: selectedDataType,
          })

          return {
            key: item.key,
            name: item.name,
            file: item.file,
            path: item.path,
            metadata: {
              dataset_id: mode === 'existing' ? selectedDatasetId : undefined,
              dataset_name: mode === 'new' ? newDatasetName : undefined,
              source_organ: mode === 'new' ? (resolvedDatasetSource || undefined) : undefined,
              aggregation_level: dataLevel,
              is_public: mode === 'new' ? isPublic : undefined,
              task_type: taskType,
              label: isSegmentation ? undefined : '',
              case_id: '',
              age: undefined,
              gender: '',
              event_time: undefined,
              event_status: undefined
            },
            associatedFiles: matchedSegmentationJson
              ? [matchedSegmentationJson]
              : (item.type === 'mrxs' || item.type === 'tmap')
                ? item.associatedFiles
                : undefined
          }
        })

      const taskId = await addUploadTask(uploadTasks)
      setUploadStatus('success')
      setSubmittedTaskId(taskId)
      const datasetNameForCallback = mode === 'new' ? newDatasetName : t('chatComponents.datasetRegistration.existingDataset')
      if (onUploadStarted) onUploadStarted(taskId, readyUploadCount, datasetNameForCallback, mode)
      
    } catch (error) {
      console.error('Upload failed', error)
      setValidationErrors([error instanceof Error ? error.message : t('chatComponents.datasetRegistration.registrationFailed')])
      setUploadStatus('error')
      if (onError) onError(error instanceof Error ? error.message : t('chatComponents.datasetRegistration.registrationFailed'))
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden w-full max-w-2xl mb-4">
      <div className="px-5 py-4 bg-gradient-to-r from-primary-50 to-blue-50 border-b border-gray-100 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-primary-600" />
          <h3 className="font-semibold text-gray-900">{t('chatComponents.datasetRegistration.title')}</h3>
        </div>
      </div>

      <div className="p-5 space-y-5">
        {uploadStatus === 'success' ? (
          (() => {
            const displayFileCount = config?.submitted_file_count ?? readyUploadCount
            const displayDatasetName = config?.submitted_dataset_name ?? (mode === 'new' ? newDatasetName : t('chatComponents.datasetRegistration.existingDataset'))
            const displayMode = config?.submitted_mode ?? mode

            return (
              <div className="space-y-4">
                <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start sm:items-center gap-3">
                  <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5 sm:mt-0" />
                  <div>
                    <h4 className="text-sm font-semibold text-green-800">{t('chatComponents.datasetRegistration.registrationStarted')}</h4>
                    <p className="text-xs text-green-700 mt-1 leading-relaxed">
                      {t('chatComponents.datasetRegistration.registrationStartedDesc', { count: displayFileCount, name: displayDatasetName })}
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg p-3">
                  <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs text-amber-800 font-medium">
                      {t('chatComponents.datasetRegistration.doNotRefresh')}
                    </p>
                    <p className="text-xs text-amber-700 mt-0.5">
                      {t('chatComponents.datasetRegistration.doNotRefreshDesc')}
                    </p>
                  </div>
                </div>

                {isSegmentation && segMissingMasks && (
                  <div className="flex items-start gap-3 bg-orange-50 border border-orange-200 rounded-lg p-3">
                    <AlertTriangle className="w-5 h-5 text-orange-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs text-orange-800 font-medium">{t('chatComponents.datasetRegistration.segBestEffortTitle')}</p>
                      <p className="text-xs text-orange-700 mt-1 leading-relaxed">
                        {t('chatComponents.datasetRegistration.segBestEffortDesc')}
                      </p>
                    </div>
                  </div>
                )}

                {!helpfulnessFeedback && (
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <p className="text-sm font-medium text-blue-800 mb-3">{t('chatComponents.datasetRegistration.feedbackQuestion')}</p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setHelpfulnessFeedback('helpful')
                          if (messageId && onHelpfulnessFeedback) {
                            onHelpfulnessFeedback(messageId, 'helpful', submittedTaskId, 'registration', displayMode === 'new' ? displayDatasetName : 'Dataset Registration')
                          }
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-blue-200 hover:bg-green-50 hover:border-green-300 hover:text-green-700 text-blue-700 rounded-md text-sm font-medium transition-all shadow-sm"
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                        {t('chatComponents.datasetRegistration.yes')}
                      </button>
                      <button
                        onClick={() => {
                          setHelpfulnessFeedback('not_helpful')
                          if (messageId && onHelpfulnessFeedback) {
                            onHelpfulnessFeedback(messageId, 'not_helpful', submittedTaskId, 'registration', displayMode === 'new' ? displayDatasetName : 'Dataset Registration')
                          }
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-blue-200 hover:bg-red-50 hover:border-red-300 hover:text-red-700 text-blue-700 rounded-md text-sm font-medium transition-all shadow-sm"
                      >
                        <ThumbsDown className="w-3.5 h-3.5" />
                        {t('chatComponents.datasetRegistration.no')}
                      </button>
                    </div>
                  </div>
                )}

                {helpfulnessFeedback && (
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 flex items-center gap-2">
                    {helpfulnessFeedback === 'helpful' ? (
                      <ThumbsUp className="w-4 h-4 text-green-500" />
                    ) : (
                      <ThumbsDown className="w-4 h-4 text-red-500" />
                    )}
                    <p className="text-sm text-gray-600 font-medium">
                      {t('chatComponents.datasetRegistration.thankYouFeedback')}
                    </p>
                  </div>
                )}
              </div>
            )
          })()
        ) : (
          <>
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">{t('chatComponents.datasetRegistration.registrationMode')}</label>
                  <div className="grid grid-cols-2 gap-1 p-1 bg-gray-100 rounded-lg">
                    <button
                      onClick={() => setMode('new')}
                      className={`text-xs font-medium py-2 px-1 rounded-md transition-all text-center ${
                        mode === 'new' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      {t('chatComponents.datasetRegistration.newDataset')}
                    </button>
                    <button
                      onClick={() => setMode('existing')}
                      className={`text-xs font-medium py-2 px-1 rounded-md transition-all text-center ${
                        mode === 'existing' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      {t('chatComponents.datasetRegistration.updateExisting')}
                    </button>
                  </div>
                </div>

                <div>
                  {mode === 'new' ? (
                    <>
                      <label className="block text-sm font-medium text-gray-700 mb-1">{t('chatComponents.datasetRegistration.datasetName')}</label>
                      <input
                        type="text"
                        value={newDatasetName}
                        onChange={(e) => setNewDatasetName(e.target.value)}
                        placeholder={t('chatComponents.datasetRegistration.datasetNamePlaceholder')}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100 h-[38px]"
                      />
                    </>
                  ) : (
                    <>
                      <label className="block text-sm font-medium text-gray-700 mb-1">{t('chatComponents.datasetRegistration.selectDatasetLabel')}</label>
                      {loadingDatasets ? (
                        <div className="flex items-center gap-2 text-sm text-gray-500 py-2 h-[38px]">
                           <Loader2 className="w-4 h-4 animate-spin" /> {t('chatComponents.datasetRegistration.loading')}
                        </div>
                       ) : (
                         <Select
                           value={selectedDatasetId}
                           onChange={setSelectedDatasetId}
                           options={filteredDatasets.map(d => ({
                             value: d.dataset_id || '',
                             label: t('chatComponents.datasetRegistration.datasetWithSource', {
                               name: d.dataset_name,
                               source: getDatasetSource(d),
                             }),
                           }))}
                           placeholder={t('chatComponents.datasetRegistration.chooseDataset')}
                         />
                       )}

                      {!loadingDatasets && selectedDataset && (
                        <p className="mt-2 text-xs text-gray-500">
                          {t('chatComponents.datasetRegistration.sourceLabel', {
                            source: getDatasetSource(selectedDataset)
                          })}
                        </p>
                      )}
                    </>
                  )}
                </div>
              </div>

              <div className="w-full">
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('chatComponents.datasetRegistration.dataGrouping')}</label>
                <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => setDataLevel('file')}
                      className={`border rounded-lg p-3 flex flex-col items-center gap-1 transition-all ${
                        dataLevel === 'file' 
                          ? 'bg-primary-50 border-primary-200 text-primary-700' 
                          : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        <FileIcon className={`w-3.5 h-3.5 ${dataLevel === 'file' ? 'text-primary-600' : 'text-gray-400'}`} />
                        <span className="text-sm font-medium">{t('chatComponents.datasetRegistration.fileLevel')}</span>
                      </div>
                      <span className="text-xs opacity-75 hidden sm:inline">{t('chatComponents.datasetRegistration.fileLevelDesc')}</span>
                    </button>
                    
                    <button
                      onClick={() => !isSegmentation && setDataLevel('case')}
                      disabled={isSegmentation}
                      className={`border rounded-lg p-3 flex flex-col items-center gap-1 transition-all ${
                        isSegmentation
                          ? 'bg-gray-50 border-gray-200 text-gray-400 cursor-not-allowed opacity-60'
                          : dataLevel === 'case'
                            ? 'bg-primary-50 border-primary-200 text-primary-700'
                            : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        <FolderPlus className={`w-3.5 h-3.5 ${isSegmentation ? 'text-gray-300' : dataLevel === 'case' ? 'text-primary-600' : 'text-gray-400'}`} />
                        <span className="text-sm font-medium">{t('chatComponents.datasetRegistration.caseLevel')}</span>
                      </div>
                      <span className="text-xs opacity-75 hidden sm:inline">
                        {isSegmentation
                          ? t('chatComponents.datasetRegistration.segmentationFileLevelOnly')
                          : t('chatComponents.datasetRegistration.caseLevelDesc')
                        }
                      </span>
                    </button>
                </div>
              </div>

              {mode === 'new' && (
                <div className="w-full">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {t('uploadComponents.datasetConfig.sourceOrganTissue')}
                  </label>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    <Select
                      value={datasetSourceSelection}
                      onChange={setDatasetSourceSelection}
                      options={[
                        ...organSources.filter((source) => source !== 'Other').map((source) => ({
                          value: source,
                          label: t(`organSources.${organSourceKeyMap[source]}`),
                        })),
                        { value: 'Other', label: t('organSources.other') },
                      ]}
                      placeholder={t('uploadComponents.datasetConfig.selectDatasetSource')}
                    />
                    <input
                      type="text"
                      value={isOtherSource ? datasetSourceCustom : ''}
                      onChange={(e) => setDatasetSourceCustom(e.target.value)}
                      disabled={!isOtherSource}
                      placeholder={isOtherSource
                        ? t('uploadComponents.datasetConfig.otherSourcePlaceholder')
                        : t('uploadComponents.datasetConfig.selectDatasetSource')}
                      className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-primary-100 h-[38px] ${
                        !isOtherSource
                          ? 'bg-gray-100 border-gray-200 cursor-not-allowed opacity-60'
                          : 'bg-white border-gray-200'
                      }`}
                    />
                  </div>
                  <p className="mt-2 text-xs text-gray-500">
                    {t('uploadComponents.datasetConfig.datasetSourceDescription')}
                  </p>
                </div>
              )}

              {mode === 'new' && (
                <div className="w-full">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {t('uploadComponents.datasetConfig.datasetVisibility')}
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setIsPublic(false)}
                      className={`border rounded-lg p-3 text-left transition-all ${
                        !isPublic
                          ? 'bg-primary-50 border-primary-200 text-primary-700'
                          : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <div className="text-sm font-medium">{t('uploadComponents.datasetConfig.private')}</div>
                      <div className="text-xs opacity-80">{t('uploadComponents.datasetConfig.privateDesc')}</div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setIsPublic(true)}
                      className={`border rounded-lg p-3 text-left transition-all ${
                        isPublic
                          ? 'bg-primary-50 border-primary-200 text-primary-700'
                          : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <div className="text-sm font-medium">{t('uploadComponents.datasetConfig.public')}</div>
                      <div className="text-xs opacity-80">{t('uploadComponents.datasetConfig.publicDesc')}</div>
                    </button>
                  </div>
                </div>
              )}

            </div>

            <div
              className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors ${
                 isDragging ? 'border-primary-500 bg-primary-50' : 'border-gray-200 hover:border-gray-300'
              } ${readyUploadCount > 0 ? 'bg-gray-50' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
            >
              {isCollecting ? (
                <div className="space-y-3">
                  <div className="w-10 h-10 bg-primary-100 rounded-full flex items-center justify-center mx-auto">
                    <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{t('chatComponents.datasetRegistration.collectionProgressTitle')}</p>
                    <p className="text-xs text-gray-500 mt-1">{t('chatComponents.datasetRegistration.collectionProgressDescription')}</p>
                  </div>
                  <div className="text-xs text-gray-500 space-y-1">
                    <p>
                      {t('chatComponents.datasetRegistration.collectionProgressStats', {
                        files: collectionProgress?.discoveredFiles ?? 0,
                        directories: collectionProgress?.discoveredDirectories ?? 0,
                      })}
                    </p>
                    {collectionProgress?.currentDirectoryName && (
                      <p>{t('chatComponents.datasetRegistration.collectionProgressCurrentDirectory', { name: collectionProgress.currentDirectoryName })}</p>
                    )}
                  </div>
                </div>
              ) : readyUploadCount > 0 ? (
                <div className="space-y-3">
                  <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center mx-auto">
                    <CheckCircle className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{t('chatComponents.datasetRegistration.filesSelected', { count: readyUploadCount })}</p>
                    <p className="text-xs text-gray-500">{t('chatComponents.datasetRegistration.readyToRegister')}</p>
                  </div>
                  <button 
                    onClick={clearSelection}
                    className="text-xs text-red-600 hover:text-red-700 underline"
                  >
                    {t('chatComponents.datasetRegistration.clearSelection')}
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <UploadCloud className="w-8 h-8 text-gray-400 mx-auto" />
                  <div>
                    <p className="text-sm font-medium text-gray-900">{t('chatComponents.datasetRegistration.dragDropFolder')}</p>
                    <p className="text-xs text-gray-500 mt-1">
                      {isSegmentation
                        ? t('chatComponents.datasetRegistration.dragDropFolderDescSegmentation')
                        : t('chatComponents.datasetRegistration.dragDropFolderDesc')
                      }
                    </p>
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end pr-1">
              <button 
                onClick={handleDownloadTemplate}
                className="flex items-center gap-1.5 text-xs text-primary-600 hover:text-primary-700 hover:underline"
              >
                <Download className="w-3 h-3" />
                {(() => {
                  let modeLabel = t('chatComponents.datasetRegistration.classification')
                  const resolvedMode = mode === 'existing' && selectedDatasetId
                    ? datasets.find(d => d.dataset_id === selectedDatasetId)?.task_type
                    : config?.upload_mode
                  const resolvedFamily = getTaskFamily(resolvedMode)
                  if (resolvedFamily === 'survival') modeLabel = t('chatComponents.datasetRegistration.survival')
                  else if (resolvedFamily === 'segmentation') modeLabel = t('chatComponents.datasetRegistration.segmentation')
                  return t('chatComponents.datasetRegistration.downloadTemplate', { mode: modeLabel })
                })()}
              </button>
            </div>

            {validationErrors.length > 0 && (
              <div className="bg-red-50 border border-red-100 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                   <AlertTriangle className="w-4 h-4 text-red-600" />
                   <span className="text-xs font-bold text-red-800">{t('chatComponents.datasetRegistration.formatIssue')}</span>
                </div>
                {validationErrors.map((err, i) => (
                  <p key={i} className="text-xs text-red-700 ml-6 list-disc">• {err}</p>
                ))}
              </div>
            )}

             <button
                onClick={handleStartUpload}
               disabled={isUploading || isCollecting || readyUploadCount === 0}
               className="w-full py-2 bg-primary-600 text-white rounded-lg text-sm font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
             >
              {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
              {t('chatComponents.datasetRegistration.startRegistration')}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
