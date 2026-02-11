import { Layers, RefreshCw, Minus, Plus, CheckCircle, Cpu } from 'lucide-react'
import { Card } from '../ui/card'
import { QueueStatus } from '../../api'

export interface TasksTabProps {
  queueStatus: QueueStatus | null
  loadingQueue: boolean
  queueError: string | null
  taskTimeout: string
  taskSaving: boolean
  taskSaved: boolean
  onLoadQueueStatus: () => void
  onUpdateMaxConcurrent: (value: number) => void
  onTaskTimeoutChange: (value: string) => void
  onTaskSave: (e: React.FormEvent) => void
}

export function TasksTab({
  queueStatus,
  loadingQueue,
  queueError,
  taskTimeout,
  taskSaving,
  taskSaved,
  onLoadQueueStatus,
  onUpdateMaxConcurrent,
  onTaskTimeoutChange,
  onTaskSave
}: TasksTabProps) {
  const isSingleGPU = queueStatus?.gpu_count === 1

  return (
    <div className="space-y-6">
      <Card className="p-4 sm:p-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
          <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
            <Layers className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
            <span className="break-words">Task Processing Configuration</span>
          </h2>
          <div className="flex items-center gap-3 self-end sm:self-auto">
            {queueStatus && (
              <div className="flex items-center gap-1.5 px-2 py-1 bg-blue-50 rounded-md">
                <Cpu className="w-4 h-4 text-blue-600" />
                <span className="text-sm font-medium text-blue-700">
                  {queueStatus.gpu_count} GPU{queueStatus.gpu_count !== 1 ? 's' : ''}
                </span>
              </div>
            )}
            <button
              onClick={onLoadQueueStatus}
              disabled={loadingQueue}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              title="Refresh queue status"
            >
              <RefreshCw className={`w-4 h-4 ${loadingQueue ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {queueError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {queueError}
          </div>
        )}

        {queueStatus ? (
          <div className="space-y-6">
            {/* Compact Status Bar */}
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-8 items-center">
                {/* Left Column: Queue State + Running Tasks */}
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 w-full">
                  <div className="flex items-center gap-3 min-w-fit flex-shrink-0 justify-between sm:justify-start">
                    <div className="flex items-center gap-3">
                      <div className={`w-3 h-3 rounded-full flex-shrink-0 ${queueStatus.is_running ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-red-500'}`} />
                      <span className="text-sm font-bold text-gray-700 whitespace-nowrap">
                        {queueStatus.is_running ? 'Queue Active' : 'Queue Stopped'}
                      </span>
                    </div>
                  </div>
                  <div className="hidden sm:block w-px h-6 bg-gray-300 mx-1" />
                  <div className="flex-1 flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-gray-200 shadow-sm min-w-0">
                    <span className="text-sm font-medium text-gray-500 truncate mr-2">Running Tasks</span>
                    <span className="text-base font-bold text-gray-900">{queueStatus.running_count}</span>
                  </div>
                </div>
                {/* Right Column: Pending Tasks */}
                <div className="w-full">
                  <div className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-gray-200 shadow-sm w-full">
                    <span className="text-sm font-medium text-gray-500 truncate">Pending Tasks</span>
                    <span className="text-base font-bold text-gray-900">{queueStatus.pending_count}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Settings Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
              {/* Max Concurrent */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Max Concurrent Tasks
                </label>
                <div className="flex flex-col gap-2">
                  <div className="flex items-center w-full">
                    <div className={`flex items-center bg-white border border-gray-300 rounded-lg overflow-hidden shadow-sm transition-colors w-full ${isSingleGPU ? 'opacity-50 cursor-not-allowed' : 'hover:border-primary-400'}`}>
                      <button
                        onClick={() => onUpdateMaxConcurrent(Math.max(1, queueStatus.max_concurrent - 1))}
                        disabled={isSingleGPU}
                        className={`p-2.5 text-gray-600 transition-colors border-r border-gray-200 flex-shrink-0 ${isSingleGPU ? 'cursor-not-allowed' : 'hover:bg-gray-50 active:bg-gray-100'}`}
                        title={isSingleGPU ? 'Disabled: Single GPU' : 'Decrease'}
                      >
                        <Minus className="w-4 h-4" />
                      </button>
                      <input
                        type="number"
                        min="1"
                        max="10"
                        value={queueStatus.max_concurrent}
                        disabled={isSingleGPU}
                        onChange={(e) => {
                          const val = parseInt(e.target.value);
                          if (!isNaN(val)) {
                            onUpdateMaxConcurrent(Math.min(10, Math.max(1, val)));
                          }
                        }}
                        className={`flex-1 py-1.5 text-center font-bold text-gray-900 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none bg-transparent text-sm ${isSingleGPU ? 'cursor-not-allowed' : ''}`}
                      />
                      <button
                        onClick={() => onUpdateMaxConcurrent(Math.min(10, queueStatus.max_concurrent + 1))}
                        disabled={isSingleGPU}
                        className={`p-2.5 text-gray-600 transition-colors border-l border-gray-200 flex-shrink-0 ${isSingleGPU ? 'cursor-not-allowed' : 'hover:bg-gray-50 active:bg-gray-100'}`}
                        title={isSingleGPU ? 'Disabled: Single GPU' : 'Increase'}
                      >
                        <Plus className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                  {isSingleGPU ? (
                    <p className="text-xs text-amber-600 leading-tight">
                      Concurrency is not configurable on systems with a single GPU.
                    </p>
                  ) : (
                    <p className="text-xs text-gray-500 leading-tight">
                      Controls how many GPU tasks run in parallel. High values need more VRAM.
                    </p>
                  )}
                </div>
              </div>

              {/* Timeout */}
              <div>
                <form onSubmit={onTaskSave} className="flex flex-col gap-2 h-full justify-between">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Task Timeout (seconds)
                    </label>
                    <div className="flex items-center gap-0 w-full rounded-lg shadow-sm overflow-hidden border border-gray-300 focus-within:ring-2 focus-within:ring-primary-500 focus-within:border-transparent transition-all">
                      <input
                        type="number"
                        value={taskTimeout}
                        onChange={(e) => onTaskTimeoutChange(e.target.value)}
                        min="60"
                        max="259200"
                        className="flex-1 px-3 py-2 border-none focus:ring-0 text-sm font-medium"
                        placeholder="86400"
                      />
                      <button
                        type="submit"
                        disabled={taskSaving}
                        className={`flex-shrink-0 px-4 py-2 text-sm font-bold text-white transition-all active:scale-95 border-l border-gray-300 ${taskSaved
                          ? 'bg-green-600 hover:bg-green-700'
                          : taskSaving
                            ? 'bg-gray-400 cursor-not-allowed'
                            : 'bg-primary-600 hover:bg-primary-700'
                          } focus:outline-none`}
                      >
                        {taskSaved ? (
                          <span className="flex items-center">
                            <CheckCircle className="w-3.5 h-3.5 mr-1.5" />
                            Saved
                          </span>
                        ) : taskSaving ? 'Saving...' : 'Save'}
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 italic">
                    Tasks auto-cancel after this limit (Max: 3 days).
                  </p>
                </form>
              </div>
            </div>

            {/* Task List (if active) */}
            {(queueStatus.running_tasks?.length > 0 || queueStatus.pending_task_ids.length > 0) && (
              <div className="pt-4 border-t border-gray-100 space-y-3">
                {queueStatus.running_tasks?.length > 0 && (
                  <div className="flex items-start gap-3">
                    <span className="text-xs font-bold text-gray-500 uppercase tracking-wider py-0.5 min-w-[60px]">Running:</span>
                    <div className="flex flex-wrap gap-2">
                      {queueStatus.running_tasks.map((task) => (
                        <span key={task.task_id} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-green-50 text-green-700 border border-green-100">
                          {task.task_id.length > 8 ? `${task.task_id.slice(0, 8)}...` : task.task_id}
                          {task.gpu !== null && (
                            <span className="ml-1 px-1 bg-blue-100 text-blue-700 rounded text-[9px]">
                              GPU{task.gpu}
                            </span>
                          )}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {queueStatus.pending_task_ids.length > 0 && (
                  <div className="flex items-start gap-3">
                    <span className="text-xs font-bold text-gray-500 uppercase tracking-wider py-0.5 min-w-[60px]">Pending:</span>
                    <div className="flex flex-wrap gap-2">
                      {queueStatus.pending_task_ids.map((taskId) => (
                        <span key={taskId} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-100">
                          {taskId.length > 8 ? `${taskId.slice(0, 8)}...` : taskId}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : loadingQueue ? (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="w-8 h-8 animate-spin text-primary-500 opacity-50" />
          </div>
        ) : (
          <div className="text-center py-12 bg-gray-50 rounded-xl border border-dashed border-gray-200 text-gray-500">
            Unable to load queue status. Please check service connectivity.
          </div>
        )}
      </Card>
    </div>
  )
}
