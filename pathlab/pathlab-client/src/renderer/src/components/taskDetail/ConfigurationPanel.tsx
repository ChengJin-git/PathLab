import React from 'react'
import { Layers, Brain, Activity } from 'lucide-react'
import { Card } from '../ui/card'
import { TaskDetail } from './types'

interface ConfigurationPanelProps {
  task: TaskDetail
}

export const ConfigurationPanel: React.FC<ConfigurationPanelProps> = ({ task }) => {
  const isExternalValidation = task.task_type === 'external_validation'

  return (
    <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
      <h3 className="text-sm sm:text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
        <Layers className="w-4 h-4 sm:w-5 sm:h-5 text-gray-700" />
        Configuration
      </h3>

      {isExternalValidation ? (
        /* External validation: show source model & target dataset info */
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Brain className="w-3.5 h-3.5 text-purple-600" />
              Source Model
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Model ID</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm font-mono text-[10px] sm:text-xs truncate max-w-[180px]" title={task.model_config.model_id}>
                  {task.model_config.model_id || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Training Task</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm font-mono text-[10px] sm:text-xs truncate max-w-[180px]" title={task.model_config.model_task_id}>
                  {task.model_config.model_task_id || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Feature Extractor</span>
                <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                  {task.preprocessing_config.feature_extractor || 'N/A'}
                </span>
              </div>
              {task.data_type === 'wsi' && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">Aggregator</span>
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
              Target Dataset
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Dataset ID</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm font-mono text-[10px] sm:text-xs truncate max-w-[180px]" title={task.model_config.dataset_id}>
                  {task.model_config.dataset_id || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Total WSIs</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.total_wsi ?? task.wsi_count ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Data Level</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm uppercase">
                  {task.data_type || 'N/A'}
                </span>
              </div>
              {task.classes && task.classes.length > 0 && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">Classes</span>
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
              Preprocessing
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Saturation Threshold</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.preprocessing_config.sthresh ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Mask Threshold</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.preprocessing_config.mthresh ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Use Otsu</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.preprocessing_config.use_otsu !== undefined
                    ? (task.preprocessing_config.use_otsu ? 'Yes' : 'No')
                    : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Extractor</span>
                <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                  {task.preprocessing_config.feature_extractor || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Feature Batch Size</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.preprocessing_config.feature_batch_size ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Brain className="w-3.5 h-3.5 text-purple-600" />
              Model & Training
            </h4>
            <div className="space-y-3">
              {task.data_type === 'wsi' && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">Aggregator</span>
                  <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100 shadow-sm">
                    {task.model_config.aggregator?.toUpperCase() || 'N/A'}
                  </span>
                </div>
              )}
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Learning Rate</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.learning_rate ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Epochs</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.epochs ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Optimizer</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm uppercase">
                  {task.model_config.optimizer || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Training Batch Size</span>
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
