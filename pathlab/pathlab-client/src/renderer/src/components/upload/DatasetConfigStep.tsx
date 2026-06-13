import React, { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ArrowRight, Tags, Activity, Users, FileImage, Plus, Layers, Info, Database, Globe, Lock } from 'lucide-react'
import { PageHeader } from '../PageHeader'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Select } from '../ui/select'
import { useDebounce } from '../../lib/useDebounce'
import type { UploadMode, DataLevel } from './types'
import { organSources, organSourceKeyMap } from '../../constants/wsi'

export interface DatasetConfigStepProps {
  datasetName: string
  onDatasetNameChange: (name: string) => void
  uploadMode: UploadMode
  onUploadModeChange: (mode: UploadMode) => void
  dataLevel: DataLevel
  onDataLevelChange: (level: DataLevel) => void
  datasetSourceSelection: string
  datasetSourceCustom: string
  onDatasetSourceSelectionChange: (value: string) => void
  onDatasetSourceCustomChange: (value: string) => void
  isExistingDataset: boolean
  existingDatasets: string[]
  showValidation: boolean
  fromAIChat: boolean
  existingDatasetSource?: string
  isPublic: boolean
  onIsPublicChange: (value: boolean) => void
  onNext: () => void
  onBack: () => void
}

export const DatasetConfigStep: React.FC<DatasetConfigStepProps> = ({
  datasetName, onDatasetNameChange, uploadMode, onUploadModeChange,
  dataLevel, onDataLevelChange, datasetSourceSelection, datasetSourceCustom,
  onDatasetSourceSelectionChange, onDatasetSourceCustomChange, isExistingDataset, existingDatasets,
  showValidation, fromAIChat, existingDatasetSource, isPublic, onIsPublicChange,
  onNext, onBack
}) => {
  const { t } = useTranslation()
  const [debouncedSourceCustom, setDebouncedSourceCustom] = useState(datasetSourceCustom)
  const _debouncedForParent = useDebounce(debouncedSourceCustom, 300)

  const isSegmentation = uploadMode === 'segmentation'
  const isOtherSource = datasetSourceSelection === 'Other'
  const canEditSource = true
  const sourceCustomPlaceholder = isOtherSource
    ? t('uploadComponents.datasetConfig.otherSourcePlaceholder')
    : datasetSourceSelection
      ? ''
      : t('uploadComponents.datasetConfig.selectDatasetSource')

  // Sync external datasetSourceCustom changes (e.g., when selection changes to non-Other)
  useEffect(() => {
    if (!isOtherSource) {
      setDebouncedSourceCustom('')
    }
  }, [isOtherSource])

  // Handle debounced input for custom source
  useEffect(() => {
    onDatasetSourceCustomChange(_debouncedForParent)
  }, [_debouncedForParent, onDatasetSourceCustomChange])

  // Auto-fill source for existing datasets
  useEffect(() => {
    if (isExistingDataset && existingDatasetSource) {
      if (organSources.includes(existingDatasetSource)) {
        // Source is in the select options
        onDatasetSourceSelectionChange(existingDatasetSource)
      } else {
        // Source is not in options, put in "Other" + custom field
        onDatasetSourceSelectionChange('Other')
        setDebouncedSourceCustom(existingDatasetSource)
      }
    }
  }, [isExistingDataset, existingDatasetSource, onDatasetSourceSelectionChange])

  // When switching to segmentation, force data level to 'file' (patch-only)
  const handleUploadModeChange = useCallback((mode: UploadMode) => {
    onUploadModeChange(mode)
    if (mode === 'segmentation') {
      onDataLevelChange('file')
    }
  }, [onUploadModeChange, onDataLevelChange])

  return (
    <>
      <div className="flex-none mb-2">
        <PageHeader title={t('uploadComponents.datasetConfig.registerFiles')} description={t('uploadComponents.datasetConfig.prepareAndRegister')}>
          <Button variant="outline" onClick={onBack} className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            {fromAIChat ? t('uploadComponents.datasetConfig.backToChat') : t('uploadComponents.datasetConfig.backToDashboard')}
          </Button>
        </PageHeader>
      </div>
      <div className="flex-1 flex flex-col items-center px-4 pt-2 pb-4">
        <div className="w-full max-w-4xl">
          <Card className="p-5 sm:p-8 shadow-xl border-slate-100 rounded-[1.5rem] sm:rounded-[2rem] overflow-hidden">
            <div className="flex flex-col gap-6 sm:gap-8">
              <div>
                <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">{t('uploadComponents.datasetConfig.datasetName')}</label>
                <div className="relative">
                  <input
                    type="text"
                    className={`w-full px-4 sm:px-5 py-3 sm:py-4 text-base sm:text-lg border rounded-xl sm:rounded-2xl focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all ${showValidation && !datasetName.trim()
                      ? 'border-red-500 bg-red-50'
                      : 'border-slate-200 bg-slate-50/50 hover:border-slate-300'
                      }`}
                    placeholder={t('uploadComponents.datasetConfig.datasetNamePlaceholder')}
                    value={datasetName}
                    onChange={e => onDatasetNameChange(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && datasetName.trim() && onNext()}
                    autoFocus
                  />
                  {isExistingDataset && (
                    <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-1.5 px-3 py-1 bg-amber-50 text-amber-600 rounded-full text-xs font-bold border border-amber-100">
                      <Plus className="w-3 h-3" />
                      {t('uploadComponents.datasetConfig.existingDataset')}
                    </div>
                  )}
                </div>
                {existingDatasets.length > 0 && !datasetName.trim() && (
                  <div className="mt-5 p-4 sm:p-5 bg-slate-50/80 rounded-xl sm:rounded-2xl border border-slate-200 shadow-sm">
                    <div className="flex items-center gap-2 mb-3 sm:mb-4">
                      <Database className="w-4 h-4 text-slate-500" />
                      <p className="text-xs sm:text-sm font-semibold text-slate-700 uppercase tracking-wider">
                        {t('uploadComponents.datasetConfig.orSelectExisting')}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 sm:gap-2.5">
                      {existingDatasets.slice(0, 8).map(name => (
                        <button
                          key={name}
                          type="button"
                          onClick={() => onDatasetNameChange(name)}
                          className="px-3 py-1.5 sm:px-4 sm:py-2 text-xs sm:text-sm bg-white border border-slate-200 text-slate-700 rounded-lg sm:rounded-xl hover:border-blue-400 hover:text-blue-700 hover:bg-blue-50/50 hover:shadow-md transition-all text-left font-medium"
                        >
                          {name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <p className="mt-3 text-sm text-slate-400">
                  {isExistingDataset
                    ? t('uploadComponents.datasetConfig.existingDatasetHint')
                    : t('uploadComponents.datasetConfig.newDatasetHint')}
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 sm:gap-8 items-stretch">
                <div className="flex flex-col">
                  <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">{t('uploadComponents.datasetConfig.analysisType')}</label>
                  <div className="grid grid-cols-1 gap-3 sm:gap-4 flex-1">
                    <button
                      onClick={() => !isExistingDataset && handleUploadModeChange('classification')}
                      disabled={isExistingDataset}
                      className={`flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${uploadMode === 'classification'
                        ? 'border-blue-500 bg-blue-50/50'
                        : `border-slate-100 bg-white ${!isExistingDataset ? 'hover:border-slate-200' : ''}`
                        } ${isExistingDataset ? 'cursor-not-allowed' : ''} ${isExistingDataset && uploadMode !== 'classification' ? 'opacity-40' : ''}`}
                    >
                      <div className={`p-2 rounded-lg mr-4 ${uploadMode === 'classification' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                        <Tags className="w-5 h-5" />
                      </div>
                      <div>
                        <span className={`font-bold block ${uploadMode === 'classification' ? 'text-blue-900' : 'text-slate-900'}`}>{t('uploadComponents.datasetConfig.classification')}</span>
                        <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">{t('uploadComponents.datasetConfig.classificationDesc')}</span>
                      </div>
                    </button>

                    <button
                      onClick={() => !isExistingDataset && handleUploadModeChange('survival')}
                      disabled={isExistingDataset}
                      className={`flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${uploadMode === 'survival'
                        ? 'border-emerald-500 bg-emerald-50/50'
                        : `border-slate-100 bg-white ${!isExistingDataset ? 'hover:border-slate-200' : ''}`
                        } ${isExistingDataset ? 'cursor-not-allowed' : ''} ${isExistingDataset && uploadMode !== 'survival' ? 'opacity-40' : ''}`}
                    >
                      <div className={`p-2 rounded-lg mr-4 ${uploadMode === 'survival' ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                        <Activity className="w-5 h-5" />
                      </div>
                      <div>
                        <span className={`font-bold block ${uploadMode === 'survival' ? 'text-emerald-900' : 'text-slate-900'}`}>{t('uploadComponents.datasetConfig.survivalAnalysis')}</span>
                        <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">{t('uploadComponents.datasetConfig.survivalDesc')}</span>
                      </div>
                    </button>

                    <button
                      onClick={() => !isExistingDataset && handleUploadModeChange('segmentation')}
                      disabled={isExistingDataset}
                      className={`flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${uploadMode === 'segmentation'
                        ? 'border-violet-500 bg-violet-50/50'
                        : `border-slate-100 bg-white ${!isExistingDataset ? 'hover:border-slate-200' : ''}`
                        } ${isExistingDataset ? 'cursor-not-allowed' : ''} ${isExistingDataset && uploadMode !== 'segmentation' ? 'opacity-40' : ''}`}
                    >
                      <div className={`p-2 rounded-lg mr-4 ${uploadMode === 'segmentation' ? 'bg-violet-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                        <Layers className="w-5 h-5" />
                      </div>
                      <div>
                        <span className={`font-bold block ${uploadMode === 'segmentation' ? 'text-violet-900' : 'text-slate-900'}`}>{t('uploadComponents.datasetConfig.segmentation')}</span>
                        <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">{t('uploadComponents.datasetConfig.segmentationDesc')}</span>
                      </div>
                    </button>
                  </div>
                </div>

                <div className="flex flex-col">
                  <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">{t('uploadComponents.datasetConfig.dataLevel')}</label>
                  <div className="flex flex-col gap-3 sm:gap-4 flex-1">
                    <button
                      onClick={() => !isExistingDataset && !isSegmentation && onDataLevelChange('case')}
                      disabled={isExistingDataset || isSegmentation}
                      className={`flex-1 flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${dataLevel === 'case'
                        ? 'border-purple-500 bg-purple-50/50'
                        : `border-slate-100 bg-white ${!isExistingDataset && !isSegmentation ? 'hover:border-slate-200' : ''}`
                        } ${isExistingDataset || isSegmentation ? 'cursor-not-allowed' : ''} ${(isExistingDataset || isSegmentation) && dataLevel !== 'case' ? 'opacity-40' : ''}`}
                    >
                      <div className={`p-2 rounded-lg mr-4 ${dataLevel === 'case' ? 'bg-purple-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                        <Users className="w-5 h-5" />
                      </div>
                      <div>
                        <span className={`font-bold block ${dataLevel === 'case' ? 'text-purple-900' : 'text-slate-900'}`}>{t('uploadComponents.datasetConfig.caseLevel')}</span>
                        <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">{t('uploadComponents.datasetConfig.caseLevelDesc')}</span>
                      </div>
                    </button>


                    <button
                      onClick={() => !isExistingDataset && onDataLevelChange('file')}
                      disabled={isExistingDataset}
                      className={`flex-1 flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${dataLevel === 'file'
                        ? 'border-orange-500 bg-orange-50/50'
                        : `border-slate-100 bg-white ${!isExistingDataset ? 'hover:border-slate-200' : ''}`
                        } ${isExistingDataset ? 'cursor-not-allowed' : ''} ${isExistingDataset && dataLevel !== 'file' ? 'opacity-40' : ''}`}
                    >
                      <div className={`p-2 rounded-lg mr-4 ${dataLevel === 'file' ? 'bg-orange-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                        <FileImage className="w-5 h-5" />
                      </div>
                      <div>
                        <span className={`font-bold block ${dataLevel === 'file' ? 'text-orange-900' : 'text-slate-900'}`}>{t('uploadComponents.datasetConfig.fileLevel')}</span>
                        <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">{t('uploadComponents.datasetConfig.fileLevelDesc')}</span>
                      </div>
                    </button>
                  </div>
                  {isSegmentation && (
                    <div className="flex items-start gap-2 mt-3 p-3 bg-violet-50 border border-violet-100 rounded-xl">
                      <Info className="w-4 h-4 text-violet-500 mt-0.5 shrink-0" />
                      <span className="text-xs text-violet-700">{t('uploadComponents.datasetConfig.segmentationPatchOnly')}</span>
                    </div>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">
                  {t('uploadComponents.datasetConfig.sourceOrganTissue')}
                </label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 sm:gap-4">
                  <Select
                    value={datasetSourceSelection}
                    onChange={onDatasetSourceSelectionChange}
                    options={[
                      ...organSources.filter((source) => source !== 'Other').map((source) => ({
                        value: source,
                        label: t(`organSources.${organSourceKeyMap[source]}`),
                      })),
                      { value: 'Other', label: t('organSources.other') },
                    ]}
                    placeholder={t('uploadComponents.datasetConfig.selectDatasetSource')}
                    disabled={!canEditSource}
                  />
                  <input
                    type="text"
                    value={isOtherSource ? debouncedSourceCustom : ''}
                    onChange={(e) => setDebouncedSourceCustom(e.target.value)}
                    disabled={!isOtherSource || !canEditSource}
                    placeholder={sourceCustomPlaceholder}
                    className={`w-full px-4 sm:px-5 py-3 border rounded-xl sm:rounded-2xl focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all ${!isOtherSource || !canEditSource
                        ? 'bg-slate-100 border-slate-200 cursor-not-allowed opacity-60'
                        : 'border-slate-200 bg-slate-50/50 hover:border-slate-300'
                      }`}
                  />
                </div>
                <p className="mt-3 text-sm text-slate-400">
                  {t('uploadComponents.datasetConfig.datasetSourceDescription')}
                </p>
              </div>

              {!isExistingDataset && (
                <div>
                  <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">
                    {t('uploadComponents.datasetConfig.datasetVisibility')}
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      type="button"
                      onClick={() => onIsPublicChange(false)}
                      className={`flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${!isPublic
                        ? 'border-slate-500 bg-slate-50/50'
                        : 'border-slate-100 bg-white hover:border-slate-200'
                        }`}
                    >
                      <div className={`p-2 rounded-lg mr-4 ${!isPublic ? 'bg-slate-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                        <Lock className="w-5 h-5" />
                      </div>
                      <div>
                        <span className={`font-bold block ${!isPublic ? 'text-slate-900' : 'text-slate-900'}`}>{t('uploadComponents.datasetConfig.private')}</span>
                        <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">{t('uploadComponents.datasetConfig.privateDesc')}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => onIsPublicChange(true)}
                      className={`flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${isPublic
                        ? 'border-blue-500 bg-blue-50/50'
                        : 'border-slate-100 bg-white hover:border-slate-200'
                        }`}
                    >
                      <div className={`p-2 rounded-lg mr-4 ${isPublic ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                        <Globe className="w-5 h-5" />
                      </div>
                      <div>
                        <span className={`font-bold block ${isPublic ? 'text-blue-900' : 'text-slate-900'}`}>{t('uploadComponents.datasetConfig.public')}</span>
                        <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">{t('uploadComponents.datasetConfig.publicDesc')}</span>
                      </div>
                    </button>
                  </div>
                </div>
              )}

              <Button
                size="lg"
                className="w-full h-14 sm:h-16 text-base sm:text-lg rounded-xl sm:rounded-2xl bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-500/20 mt-2 sm:mt-4"
                disabled={!datasetName.trim()}
                onClick={onNext}
              >
                {t('uploadComponents.datasetConfig.nextChooseFiles')} <ArrowRight className="ml-2 w-4 h-4 sm:w-5 sm:h-5" />
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
