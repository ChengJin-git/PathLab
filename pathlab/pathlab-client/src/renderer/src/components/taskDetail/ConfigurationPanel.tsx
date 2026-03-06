import React from 'react'
import { useTranslation } from 'react-i18next'
import { Layers, Brain, Activity } from 'lucide-react'
import { Card } from '../ui/card'
import { TaskDetail } from './types'
import { isSegFmEncoder } from '../../constants/training'

interface ConfigurationPanelProps {
  task: TaskDetail
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
                        <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100 shadow-sm">
                          {t('taskDetail.configuration.convDecoder')}
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
                  {task.model_config.loss_names && task.model_config.loss_names.length > 0 && (
                    <div className="text-[11px] sm:text-sm">
                      <span className="text-gray-500 font-medium block mb-2">{t('taskDetail.configuration.lossFunctions')}</span>
                      <div className="space-y-1.5">
                        {task.model_config.loss_names.map((name, i) => (
                          <div key={name} className="flex justify-between items-center">
                            <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm text-[10px] sm:text-xs">
                              {name}
                            </span>
                            <span className="font-mono text-gray-500 text-[10px] sm:text-xs">
                              {task.model_config.loss_weights?.[i] ?? '—'}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
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
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">{t('taskDetail.configuration.trainingBatchSize')}</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.batch_size ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}
