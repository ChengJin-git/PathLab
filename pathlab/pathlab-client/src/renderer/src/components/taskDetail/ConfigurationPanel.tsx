import React from 'react'
import { useTranslation } from 'react-i18next'
import { Layers, Brain, Activity } from 'lucide-react'
import { Card } from '../ui/card'
import { TaskDetail } from './types'
import { isSegFmEncoder } from '../../constants/training'

interface ConfigurationPanelProps {
  task: TaskDetail
}

const LossFunctionList: React.FC<{
  title: string
  names?: string[]
  weights?: number[]
  weightLabel: string
}> = ({ title, names, weights, weightLabel }) => {
  if (!names || names.length === 0) return null

  return (
    <div className="text-[11px] sm:text-sm">
      <span className="text-gray-500 font-medium block mb-2">{title}</span>
      <div className="flex flex-wrap gap-2">
        {names.map((name, index) => (
          <div
            key={`${name}-${index}`}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-2 py-1 shadow-sm"
          >
            <span className="font-bold text-gray-900 text-[10px] sm:text-xs">{name}</span>
            <span className="tabular-nums font-bold text-[10px] sm:text-xs text-purple-700 bg-purple-50 px-1.5 py-0.5 rounded border border-purple-100 shadow-sm">
              {weightLabel}: {weights?.[index] ?? '—'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

const formatSplitMethod = (
  splitConfig: TaskDetail['preprocessing_config']['split_config'],
  t: ReturnType<typeof useTranslation>['t']
): string => {
  if (!splitConfig) return 'N/A'
  const { strategy } = splitConfig
  if (strategy === 'random') {
    const label = t('taskDetail.configuration.splitRandom')
    if (splitConfig.ratios) {
      const { train, val, test } = splitConfig.ratios
      return `${label} (${Math.round(train * 100)}% / ${Math.round(val * 100)}% / ${Math.round(test * 100)}%)`
    }
    return label
  }
  if (strategy === 'k_fold') {
    const n = splitConfig.n_splits ?? 'K'
    return `${n}${t('taskDetail.configuration.splitKFold')}`
  }
  if (strategy === 'manual') {
    const label = t('taskDetail.configuration.splitManual')
    if (splitConfig.manual_splits && Object.keys(splitConfig.manual_splits).length > 0) {
      const counts: Record<string, number> = {}
      for (const splitType of Object.values(splitConfig.manual_splits)) {
        counts[splitType] = (counts[splitType] ?? 0) + 1
      }
      const parts = Object.entries(counts).map(([type, count]) => `${type}: ${count}`)
      return `${label} (${parts.join(' / ')})`
    }
    return label
  }
  return strategy
}

export const ConfigurationPanel: React.FC<ConfigurationPanelProps> = ({ task }) => {
  const { t } = useTranslation()
  const isExternalValidation = task.task_type === 'external_validation'
  const isSegmentation = task.task_type === 'segmentation'
  const segIsFm = isSegmentation && isSegFmEncoder(task.model_config.backbone)

  return (
    <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
      <h3 className="text-sm sm:text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
        <Layers className="w-4 h-4 sm:w-5 sm:h-5 text-gray-700" />
        {t('taskDetail.configuration.title')}
      </h3>

      {isExternalValidation ? (
        /* External validation: show source model & target dataset info */
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Brain className="w-3.5 h-3.5 text-purple-600" />
              {t('taskDetail.configuration.sourceModel')}
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.modelName')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm text-[10px] sm:text-xs truncate max-w-[180px]" title={task.model_config.model_name || task.model_config.model_id}>
                  {task.model_config.model_name || task.model_config.model_id || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.trainingTask')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm text-[10px] sm:text-xs truncate max-w-[180px]" title={task.model_config.model_task_name || task.model_config.model_task_id}>
                  {task.model_config.model_task_name || task.model_config.model_task_id || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.featureExtractor')}</span>
                <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                  {task.preprocessing_config.feature_extractor || 'N/A'}
                </span>
              </div>
              {task.data_type === 'wsi' && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">{t('taskDetail.configuration.aggregator')}</span>
                  <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100 shadow-sm">
                    {task.model_config.aggregator?.toUpperCase() || 'N/A'}
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-blue-600" />
              {t('taskDetail.configuration.targetDataset')}
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.datasetName')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm text-[10px] sm:text-xs truncate max-w-[180px]" title={task.model_config.dataset_name || task.model_config.dataset_id}>
                  {task.model_config.dataset_name || task.model_config.dataset_id || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.totalWsis')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.total_wsi ?? task.wsi_count ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.dataLevel')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm uppercase">
                  {task.data_type || 'N/A'}
                </span>
              </div>
              {task.classes && task.classes.length > 0 && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">{t('taskDetail.configuration.classes')}</span>
                  <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                    {task.classes.length}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* Regular training task: show preprocessing & training config */
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-blue-600" />
              {isSegmentation
                ? (segIsFm ? t('taskDetail.configuration.featureExtractor') : t('taskDetail.configuration.architecture'))
                : task.data_type === 'patch'
                  ? t('taskDetail.configuration.dataConfig')
                  : t('taskDetail.configuration.preprocessing')}
            </h4>
            <div className="space-y-3">
              {isSegmentation ? (
                <>
                  {segIsFm ? (
                    <>
                      <div className="flex justify-between items-center text-[11px] sm:text-sm">
                        <span className="text-gray-500 font-medium">{t('taskDetail.configuration.featureExtractor')}</span>
                        <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                          {task.model_config.backbone || 'N/A'}
                        </span>
                      </div>
                      <div className="flex justify-between items-center text-[11px] sm:text-sm">
                        <span className="text-gray-500 font-medium">{t('taskDetail.configuration.decoder')}</span>
                        <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100 shadow-sm capitalize">
                          {t(`training.modelConfig.decoder.${task.model_config.decoder_type || 'conv'}`, (task.model_config.decoder_type || 'conv').toUpperCase())}
                        </span>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="flex justify-between items-center text-[11px] sm:text-sm">
                        <span className="text-gray-500 font-medium">{t('taskDetail.configuration.architecture')}</span>
                        <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100 shadow-sm">
                          {task.model_config.architecture || 'N/A'}
                        </span>
                      </div>
                      <div className="flex justify-between items-center text-[11px] sm:text-sm">
                        <span className="text-gray-500 font-medium">{t('taskDetail.configuration.backbone')}</span>
                        <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                          {task.model_config.backbone || 'N/A'}
                        </span>
                      </div>
                    </>
                  )}
                  <LossFunctionList
                    title={t('taskDetail.configuration.lossFunctions')}
                    names={task.model_config.loss_names}
                    weights={task.model_config.loss_weights}
                    weightLabel={t('taskDetail.configuration.lossWeight')}
                  />
                </>
              ) : task.data_type === 'patch' ? (
                <>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.extractor')}</span>
                    <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                      {task.preprocessing_config.feature_extractor || 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.featureBatchSize')}</span>
                    <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                      {task.preprocessing_config.feature_batch_size ?? 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.splitMethod')}</span>
                    <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                      {formatSplitMethod(task.preprocessing_config.split_config, t)}
                    </span>
                  </div>
                </>
              ) : (
                <>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.saturationThreshold')}</span>
                    <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                      {task.preprocessing_config.sthresh ?? 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.maskThreshold')}</span>
                    <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                      {task.preprocessing_config.mthresh ?? 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.useOtsu')}</span>
                    <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                      {task.preprocessing_config.use_otsu !== undefined
                        ? (task.preprocessing_config.use_otsu ? t('taskDetail.configuration.yes') : t('taskDetail.configuration.no'))
                        : 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.extractor')}</span>
                    <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                      {task.preprocessing_config.feature_extractor || 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-[11px] sm:text-sm">
                    <span className="text-gray-500 font-medium">{t('taskDetail.configuration.featureBatchSize')}</span>
                    <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                      {task.preprocessing_config.feature_batch_size ?? 'N/A'}
                    </span>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Brain className="w-3.5 h-3.5 text-purple-600" />
              {t('taskDetail.configuration.modelAndTraining')}
            </h4>
            <div className="space-y-3">
              {!isSegmentation && task.data_type === 'wsi' && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">{t('taskDetail.configuration.aggregator')}</span>
                  <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100 shadow-sm">
                    {task.model_config.aggregator?.toUpperCase() || 'N/A'}
                  </span>
                </div>
              )}
              {!isSegmentation && task.data_type === 'patch' && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">{t('taskDetail.configuration.classifierHead')}</span>
                  <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                    {t(`taskList.classifiers.${task.model_config.classifier || 'linear'}`, t('taskList.linearProbe'))}
                  </span>
                </div>
              )}
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.learningRate')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.learning_rate ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.epochs')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.epochs ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.optimizer')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm uppercase">
                  {task.model_config.optimizer || 'N/A'}
                </span>
              </div>
              {(task.data_type === 'patch' || isSegmentation) && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">{t('taskDetail.configuration.trainingBatchSize')}</span>
                  <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                    {task.model_config.batch_size ?? 'N/A'}
                  </span>
                </div>
              )}
              {task.data_type === 'wsi' && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">{t('taskDetail.configuration.splitMethod')}</span>
                  <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                    {formatSplitMethod(task.preprocessing_config.split_config, t)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}
