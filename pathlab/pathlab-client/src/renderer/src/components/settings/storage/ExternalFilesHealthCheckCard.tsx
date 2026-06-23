import React from 'react'
import { useTranslation } from 'react-i18next'
import {
  HardDrive, Search, RefreshCw, AlertCircle,
  CheckCircle, Database
} from 'lucide-react'
import { Card } from '../../ui/card'
import { Button } from '../../ui/button'
import { CheckExternalFilesResponse } from '../../../api'
import { UnavailableFilesList } from './UnavailableFilesList'

interface ExternalFilesHealthCheckCardProps {
  checkingExternalFiles: boolean
  externalFilesResult: CheckExternalFilesResponse | null
  selectedUnavailableFiles: Set<string>
  setSelectedUnavailableFiles: React.Dispatch<React.SetStateAction<Set<string>>>
  deletingUnavailableFiles: boolean
  externalFilesError: string | null
  handleCheckExternalFiles: () => void
  handleDeleteUnavailableFiles: () => void | Promise<void>
}

export const ExternalFilesHealthCheckCard: React.FC<ExternalFilesHealthCheckCardProps> = ({
  checkingExternalFiles,
  externalFilesResult,
  selectedUnavailableFiles,
  setSelectedUnavailableFiles,
  deletingUnavailableFiles,
  externalFilesError,
  handleCheckExternalFiles,
  handleDeleteUnavailableFiles
}) => {
  const { t } = useTranslation()

  return (
    <Card className="overflow-hidden border-none shadow-xl bg-white/80 backdrop-blur-sm">
      <div className="bg-gradient-to-r from-slate-50 to-white px-6 py-5 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2.5">
            <HardDrive className="w-5 h-5 text-primary-600" />
            {t('settings.storage.externalFilesHealthCheck')}
          </h2>
          <p className="text-xs text-slate-500 mt-1 font-medium">
            {t('settings.storage.verifyAccessibility')}
          </p>
        </div>
        <Button
          onClick={handleCheckExternalFiles}
          disabled={checkingExternalFiles}
          variant={externalFilesResult ? "outline" : "default"}
          className={`gap-2.5 px-5 h-10 font-bold transition-all shadow-sm ${!externalFilesResult ? 'bg-primary-600 hover:bg-primary-700 hover:shadow-md text-white' : 'hover:bg-slate-50'}`}
        >
          {checkingExternalFiles ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              {t('settings.storage.checking')}
            </>
          ) : (
            <>
              <Search className="w-4 h-4" />
              {t('settings.storage.checkFiles')}
            </>
          )}
        </Button>
      </div>

      <div className="p-6 pt-4">
        {externalFilesError && (
          <div className="mb-4 p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 flex items-center gap-3 animate-fadeIn">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span className="text-sm font-semibold">{externalFilesError}</span>
          </div>
        )}

        {externalFilesResult && (
          <div className="space-y-6 animate-fadeIn">
            <div className="grid grid-cols-3 gap-4 mb-8">
              <div className="relative overflow-hidden bg-slate-50 p-5 rounded-2xl border border-slate-200/60 shadow-sm transition-all hover:shadow-md">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-slate-500 text-[10px] uppercase tracking-widest font-bold mb-1">{t('settings.storage.totalExternal')}</p>
                    <p className="text-3xl font-extrabold text-slate-900 tracking-tight">{externalFilesResult.total_external.toLocaleString()}</p>
                  </div>
                  <div className="p-2 bg-slate-200/50 rounded-lg">
                    <Database className="w-5 h-5 text-slate-600" />
                  </div>
                </div>
                <div className="mt-4 h-1 w-full bg-slate-200 rounded-full overflow-hidden">
                  <div className="h-full bg-slate-500 w-full opacity-30"></div>
                </div>
              </div>

              <div className="relative overflow-hidden bg-emerald-50/40 p-5 rounded-2xl border border-emerald-100 shadow-sm transition-all hover:shadow-md">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-emerald-700/70 text-[10px] uppercase tracking-widest font-bold mb-1">{t('settings.storage.available')}</p>
                    <p className="text-3xl font-extrabold text-emerald-700 tracking-tight">{externalFilesResult.available_count.toLocaleString()}</p>
                  </div>
                  <div className="p-2 bg-emerald-100/80 rounded-lg">
                    <CheckCircle className="w-5 h-5 text-emerald-600" />
                  </div>
                </div>
                <div className="mt-4 h-1 w-full bg-emerald-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 transition-all duration-1000"
                    style={{ width: `${externalFilesResult.total_external > 0 ? (externalFilesResult.available_count / externalFilesResult.total_external) * 100 : 0}%` }}
                  ></div>
                </div>
              </div>

              <div className="relative overflow-hidden bg-rose-50/40 p-5 rounded-2xl border border-rose-100 shadow-sm transition-all hover:shadow-md">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-rose-700/70 text-[10px] uppercase tracking-widest font-bold mb-1">{t('settings.storage.unavailable')}</p>
                    <p className="text-3xl font-extrabold text-rose-700 tracking-tight">{externalFilesResult.unavailable_count.toLocaleString()}</p>
                  </div>
                  <div className="p-2 bg-rose-100/80 rounded-lg">
                    <AlertCircle className="w-5 h-5 text-rose-600" />
                  </div>
                </div>
                <div className="mt-4 h-1 w-full bg-rose-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-rose-500 transition-all duration-1000"
                    style={{ width: `${externalFilesResult.total_external > 0 ? (externalFilesResult.unavailable_count / externalFilesResult.total_external) * 100 : 0}%` }}
                  ></div>
                </div>
              </div>
            </div>

            {externalFilesResult.unavailable.length > 0 && (
              <UnavailableFilesList
                unavailableFiles={externalFilesResult.unavailable}
                selectedUnavailableFiles={selectedUnavailableFiles}
                setSelectedUnavailableFiles={setSelectedUnavailableFiles}
                deletingUnavailableFiles={deletingUnavailableFiles}
                handleDeleteUnavailableFiles={handleDeleteUnavailableFiles}
              />
            )}

            {externalFilesResult.unavailable.length === 0 && externalFilesResult.total_external > 0 && (
              <div className="relative overflow-hidden p-8 bg-gradient-to-br from-emerald-50 to-teal-50/30 border border-emerald-100 rounded-3xl flex flex-col items-center text-center gap-4 animate-fadeIn shadow-inner">
                <div className="w-16 h-16 bg-white shadow-xl shadow-emerald-200/50 flex items-center justify-center rounded-2xl transform rotate-3 transition-transform hover:rotate-0 duration-500">
                  <CheckCircle className="w-8 h-8 text-emerald-500" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-emerald-900 font-black text-xl tracking-tight">{t('settings.storage.systemFullySynchronized')}</h3>
                  <p className="text-emerald-700/70 text-sm max-w-md mx-auto leading-relaxed font-medium">
                    {t('settings.storage.allFilesAccessible', { count: externalFilesResult.total_external })}
                  </p>
                </div>
                <div className="absolute top-0 right-0 p-8 opacity-[0.03] pointer-events-none transform translate-x-1/4 -translate-y-1/4 scale-150">
                  <CheckCircle className="w-48 h-48" />
                </div>
              </div>
            )}

            {externalFilesResult.total_external === 0 && (
              <div className="p-10 bg-slate-50/50 border border-dashed border-slate-200 rounded-3xl flex flex-col items-center text-center gap-4">
                <div className="p-4 bg-white rounded-2xl shadow-sm border border-slate-100">
                  <HardDrive className="w-8 h-8 text-slate-300" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-slate-900 font-bold">{t('settings.storage.noExternalFilesDetected')}</h3>
                  <p className="text-slate-500 text-sm max-w-xs">{t('settings.storage.noExternalFilesHint')}</p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
