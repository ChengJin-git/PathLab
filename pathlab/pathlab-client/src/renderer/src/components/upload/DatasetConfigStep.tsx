import React from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ArrowRight, Tags, Activity, Users, FileImage, Plus } from 'lucide-react'
import { PageHeader } from '../PageHeader'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import type { UploadMode, DataLevel } from './types'

export interface DatasetConfigStepProps {
  datasetName: string
  onDatasetNameChange: (name: string) => void
  uploadMode: UploadMode
  onUploadModeChange: (mode: UploadMode) => void
  dataLevel: DataLevel
  onDataLevelChange: (level: DataLevel) => void
  isExistingDataset: boolean
  existingDatasets: string[]
  showValidation: boolean
  fromAIChat: boolean
  onNext: () => void
  onBack: () => void
}

export const DatasetConfigStep: React.FC<DatasetConfigStepProps> = ({
  datasetName, onDatasetNameChange, uploadMode, onUploadModeChange,
  dataLevel, onDataLevelChange, isExistingDataset, existingDatasets,
  showValidation, fromAIChat, onNext, onBack
}) => {
  const { t } = useTranslation()
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
          <div className="text-center mb-6 sm:mb-8">
            <h1 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-2 sm:mb-3">{t('uploadComponents.datasetConfig.createDataset')}</h1>
            <p className="text-base sm:text-lg text-slate-500 px-4">{t('uploadComponents.datasetConfig.defineDatasetDescription')}</p>
          </div>

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
                  <div className="mt-4">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">{t('uploadComponents.datasetConfig.orSelectExisting')}</p>
                    <div className="flex flex-wrap gap-2">
                      {existingDatasets.slice(0, 8).map(name => (
                        <button
                          key={name}
                          type="button"
                          onClick={() => onDatasetNameChange(name)}
                          className="px-3 py-1.5 text-xs bg-white border border-slate-200 text-slate-600 rounded-lg hover:border-blue-500 hover:text-blue-600 transition-all shadow-sm"
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

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 sm:gap-8">
              <div>
                <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">{t('uploadComponents.datasetConfig.analysisType')}</label>
                <div className="grid grid-cols-1 gap-3 sm:gap-4">
                  <button
                    onClick={() => !isExistingDataset && onUploadModeChange('classification')}
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
                    onClick={() => !isExistingDataset && onUploadModeChange('survival')}
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
                </div>
              </div>

              <div>
                <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">{t('uploadComponents.datasetConfig.dataLevel')}</label>
                <div className="grid grid-cols-1 gap-3 sm:gap-4">
                  <button
                    onClick={() => !isExistingDataset && onDataLevelChange('case')}
                    disabled={isExistingDataset}
                    className={`flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${dataLevel === 'case'
                      ? 'border-purple-500 bg-purple-50/50'
                      : `border-slate-100 bg-white ${!isExistingDataset ? 'hover:border-slate-200' : ''}`
                      } ${isExistingDataset ? 'cursor-not-allowed' : ''} ${isExistingDataset && dataLevel !== 'case' ? 'opacity-40' : ''}`}
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
                    className={`flex flex-row items-center p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${dataLevel === 'file'
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
              </div>
              </div>

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
