import React from 'react'
import { useTranslation } from 'react-i18next'
import { ClipboardList } from 'lucide-react'
import { Card } from '../ui/card'
import { LogEntry } from './types'


interface LogViewerProps {
  logs: LogEntry[]
  logsContainerRef: React.RefObject<HTMLDivElement>
  logsEndRef: React.RefObject<HTMLDivElement>
}

export const LogViewer: React.FC<LogViewerProps> = ({
  logs,
  logsContainerRef,
  logsEndRef
}) => {
  const { t } = useTranslation()
  return (
  <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-sm sm:text-lg font-bold text-gray-900 flex items-center gap-2">
        <ClipboardList className="w-4 h-4 sm:w-5 sm:h-5 text-gray-700" />
        {t('taskDetail.logViewer.liveLogs')}
      </h3>
      <div className="flex items-center space-x-1.5 sm:space-x-2 text-[10px] sm:text-xs text-gray-400 font-medium">
        <span className="inline-block w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
        <span>{t('taskDetail.logViewer.liveStream')}</span>
      </div>
    </div>
    <div ref={logsContainerRef} className="bg-gray-950 rounded-xl p-3 sm:p-4 h-[300px] sm:h-[450px] overflow-y-auto font-mono text-[10px] sm:text-xs leading-relaxed border border-gray-800 shadow-inner scrollbar-thin scrollbar-track-gray-900 scrollbar-thumb-gray-700">
      {logs.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-600 italic">
          {t('taskDetail.logViewer.connecting')}
        </div>
      ) : (
        logs.map((log) => (
            <div
              key={log.id}
              className={`mb-1.5 break-words ${
                log.level === 'ERROR' ? 'text-red-400' :
                log.level === 'WARNING' ? 'text-yellow-400/90' :
                log.level === 'DEBUG' ? 'text-gray-500' :
                'text-emerald-400/90'
              }`}
            >
              <span className="text-gray-600 whitespace-nowrap">[{new Date(log.created_at).toLocaleTimeString([], { hour12: false })}]</span>
              {' '}
              <span className={`font-bold uppercase tracking-wider ${
                log.level === 'ERROR' ? 'text-red-500' :
                log.level === 'WARNING' ? 'text-yellow-500' :
                log.level === 'DEBUG' ? 'text-gray-600' :
                'text-blue-500'
              }`}>
                {log.level}
              </span>
              {' '}
              <span className="text-gray-300">{log.message}</span>
              {/* Display metadata for errors/warnings */}
              {log.metadata && Object.keys(log.metadata).length > 0 && (
                <div className="ml-4 mt-1 bg-white/5 p-2 rounded border border-white/5">
                  {log.metadata.error && (
                    <div className="text-red-300 font-bold">{t('taskDetail.logViewer.error')} {log.metadata.error}</div>
                  )}
                  {log.metadata.traceback && (
                    <pre className="mt-1 whitespace-pre-wrap text-red-300/60 overflow-x-auto text-[9px] sm:text-[10px]">
                      {log.metadata.traceback}
                    </pre>
                  )}
                  {/* Display other metadata excluding error/traceback */}
                  {Object.entries(log.metadata)
                    .filter(([key]) => !['error', 'traceback'].includes(key))
                    .length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 opacity-60">
                      {Object.entries(log.metadata)
                        .filter(([key]) => !['error', 'traceback'].includes(key))
                        .map(([key, value]) => (
                          <span key={key} className="text-[9px] sm:text-[10px]">
                            <span className="text-gray-400 uppercase mr-1">{key}:</span>
                            <span className="text-gray-200">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                          </span>
                        ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
      )}
      <div ref={logsEndRef} />
    </div>
  </Card>
  )
}
