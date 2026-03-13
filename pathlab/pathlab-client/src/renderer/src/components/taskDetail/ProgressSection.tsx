import React from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Circle, Loader2, XCircle, Activity } from 'lucide-react'
import { Card } from '../ui/card'
import { TaskDetail } from './types'

interface ProgressSectionProps {
  task: TaskDetail
  displayProgress: number
  isPatchLevel: boolean
  isExternalValidation: boolean
}

export const ProgressSection: React.FC<ProgressSectionProps> = ({
  task,
  displayProgress,
  isPatchLevel,
  isExternalValidation
}) => {
  const { t } = useTranslation()
  return (
  <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
    <h3 className="text-sm sm:text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
      <Activity className="w-4 h-4 sm:w-5 sm:h-5 text-primary-600" />
      {t('taskDetail.progressSection.executionProgress')}
    </h3>

    {/* Overall Progress */}
    <div className="mb-6 bg-gray-50/50 p-3 sm:p-4 rounded-xl border border-gray-100">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs sm:text-sm font-bold text-gray-600 uppercase tracking-wide">{t('taskDetail.progressSection.overallCompletion')}</span>
        <span className="text-sm sm:text-lg font-black text-primary-600">{displayProgress}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2 sm:h-3 overflow-hidden">
        <div
          className="bg-primary-600 h-full rounded-full transition-all duration-1000 ease-out shadow-sm"
          style={{ width: `${displayProgress}%` }}
        />
      </div>
    </div>

    {/* Stage Progress */}
    <div className="space-y-3">
      {isExternalValidation ? (
        /* External validation stages:
           - Patch dataset: directly Running Inference (training status)
           - WSI dataset: Patch Extraction (patching) → Feature Extraction (extracting) → Running Inference (training) */
        <>
          {!isPatchLevel && (
            <>
              {/* Stage 1: Patch Extraction */}
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center space-x-2">
                  <span className={
                    (task.status === 'extracting' || task.status === 'training' || task.status === 'completed') ? 'text-green-600' :
                    (task.status === 'patching') ? 'text-blue-600' :
                    (task.status === 'failed' && task.progress < 30) ? 'text-red-600' : 'text-gray-400'
                  }>
                    { (task.status === 'extracting' || task.status === 'training' || task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                      (task.status === 'patching') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                      (task.status === 'failed' && task.progress < 30) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
                  </span>
                  <span className={(task.status !== 'pending' && task.status !== 'queued') ? 'text-gray-900' : 'text-gray-500'}>
                    {t('taskDetail.progressSection.patchExtraction')}
                  </span>
                </div>
              </div>
              {/* Stage 2: Feature Extraction */}
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center space-x-2">
                  <span className={
                    (task.status === 'training' || task.status === 'completed') ? 'text-green-600' :
                    (task.status === 'extracting') ? 'text-blue-600' :
                    (task.status === 'failed' && task.progress >= 30 && task.progress < 70) ? 'text-red-600' : 'text-gray-400'
                  }>
                    { (task.status === 'training' || task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                      (task.status === 'extracting') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                      (task.status === 'failed' && task.progress >= 30 && task.progress < 70) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
                  </span>
                  <span className={(task.status === 'extracting' || task.status === 'training' || task.status === 'completed') ? 'text-gray-900' : 'text-gray-500'}>
                    {t('taskDetail.progressSection.featureExtraction')}
                  </span>
                </div>
              </div>
            </>
          )}
          {/* Stage 3 (or only stage for patch): Running Inference */}
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center space-x-2">
              <span className={
                (task.status === 'completed') ? 'text-green-600' :
                (task.status === 'training') ? 'text-blue-600' :
                (task.status === 'failed' && (isPatchLevel || task.progress >= 70)) ? 'text-red-600' : 'text-gray-400'
              }>
                { (task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                  (task.status === 'training') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                  (task.status === 'failed' && (isPatchLevel || task.progress >= 70)) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
              </span>
              <span className={(task.status === 'completed' || task.status === 'training') ? 'text-gray-900' : 'text-gray-500'}>
                {t('taskDetail.progressSection.runningInference')}
              </span>
            </div>
          </div>
        </>
      ) : !isPatchLevel ? (
        <>
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center space-x-2">
              <span className={
                (task.status === 'patching') ? 'text-blue-600' :
                (task.status === 'extracting' || task.status === 'training' || task.status === 'completed') ? 'text-green-600' :
                (task.status === 'failed' && task.progress < 30) ? 'text-red-600' : 'text-gray-400'
              }>
                { (task.status === 'patching') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                  (task.status === 'extracting' || task.status === 'training' || task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                  (task.status === 'failed' && task.progress < 30) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
              </span>
              <span className={(task.status !== 'pending' && task.status !== 'creating') ? 'text-gray-900' : 'text-gray-500'}>
                {t('taskDetail.progressSection.patchExtraction')}
              </span>
            </div>
            {task.patch_count && task.patch_count > 0 && (
              <span className="text-gray-600">{task.patch_count.toLocaleString()} patches</span>
            )}
          </div>

          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center space-x-2">
              <span className={
                (task.status === 'training' || task.status === 'completed') ? 'text-green-600' :
                (task.status === 'extracting') ? 'text-blue-600' :
                (task.status === 'failed' && task.progress >= 30 && task.progress < 70) ? 'text-red-600' : 'text-gray-400'
              }>
                { (task.status === 'training' || task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                  (task.status === 'extracting') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                  (task.status === 'failed' && task.progress >= 30 && task.progress < 70) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
              </span>
              <span className={(task.status === 'training' || task.status === 'completed' || task.status === 'extracting') ? 'text-gray-900' : 'text-gray-500'}>
                {t('taskDetail.progressSection.featureExtraction')}
              </span>
            </div>
            {task.processed_patches && task.patch_count && (
              <span className="text-gray-600">{task.processed_patches.toLocaleString()}/{task.patch_count.toLocaleString()}</span>
            )}
          </div>
        </>
      ) : (
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center space-x-2">
            <span className="text-green-600">
              <CheckCircle2 className="w-4 h-4" />
            </span>
            <span className="text-gray-900">
              {t('taskDetail.progressSection.dataLoading')}
            </span>
          </div>
        </div>
      )}

      {/* Model Training / Testing stage - skip for external validation (already shown above) */}
      {!isExternalValidation && (
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center space-x-2">
            <span className={
              (task.status === 'completed') ? 'text-green-600' :
              (task.status === 'training') ? 'text-purple-600' :
              (task.status === 'failed' && (isPatchLevel || task.progress >= 70)) ? 'text-red-600' : 'text-gray-400'
            }>
              { (task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                (task.status === 'training') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                (task.status === 'failed' && (isPatchLevel || task.progress >= 70)) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
            </span>
            <span className={(task.status === 'completed' || task.status === 'training') ? 'text-gray-900' : 'text-gray-500'}>
              {t('taskDetail.progressSection.modelTraining')}
            </span>
          </div>
          {task.status === 'training' && task.current_epoch && (
            <span className="text-gray-600">Epoch {task.current_epoch}/{task.model_config.epochs}</span>
          )}
        </div>
      )}
    </div>
  </Card>
  )
}
