import React from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Database } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'

export interface SuccessStepProps {
  datasetName: string
  splitUploadSuccess: string | null
  fromAIChat: boolean
  onNavigate: () => void
  onReset: () => void
}

export const SuccessStep: React.FC<SuccessStepProps> = ({
  datasetName, splitUploadSuccess, fromAIChat, onNavigate, onReset
}) => {
  const { t } = useTranslation()
  return (
    <div data-testid="success-step-root" className="flex-1 flex flex-col items-center justify-center p-4 sm:p-8">
      <Card className="w-full max-w-4xl overflow-hidden shadow-2xl border-slate-100 rounded-[1.5rem] sm:rounded-[2rem] bg-white ring-1 ring-slate-900/5 animate-in zoom-in-95 duration-300">
        <div className="grid grid-cols-1 md:grid-cols-2 min-h-[300px] md:min-h-[420px]">
          <div className="bg-slate-50/80 p-6 sm:p-10 flex flex-col justify-center items-center text-center border-b md:border-b-0 md:border-r border-slate-100">
            <div className="w-16 h-16 sm:w-20 sm:h-20 bg-green-100 text-green-600 rounded-full flex items-center justify-center mb-4 sm:mb-6 ring-8 ring-green-50 shadow-sm">
              <CheckCircle2 className="w-8 h-8 sm:w-10 sm:h-10" />
            </div>
            
            <h2 className="text-xl sm:text-2xl font-bold text-slate-900 mb-2 sm:mb-3 tracking-tight">{t('uploadComponents.successStep.importSuccessful')}</h2>
            <p className="text-sm sm:text-slate-500 mb-6 sm:mb-8 max-w-[240px] leading-relaxed">
              {t('uploadComponents.successStep.datasetUpdatedSuccessfully')}
            </p>

            <div className="flex flex-col gap-3 w-full max-w-xs">
              <Button
                size="lg"
                className="w-full h-11 text-base font-semibold bg-slate-900 hover:bg-black text-white shadow-lg shadow-slate-200"
                onClick={onNavigate}
              >
                {fromAIChat ? t('uploadComponents.successStep.goToChat') : t('uploadComponents.successStep.goToDashboard')}
              </Button>
              <Button
                variant="outline"
                className="w-full h-11 text-base border-slate-200 text-slate-600 hover:bg-white hover:border-slate-300"
                onClick={onReset}
              >
                {t('uploadComponents.successStep.uploadMore')}
              </Button>
            </div>
          </div>

          <div className="p-6 sm:p-10 flex flex-col justify-center bg-white relative">
             <h3 className="text-[10px] sm:text-xs font-bold text-slate-900 uppercase tracking-widest mb-4 sm:mb-6 border-b border-slate-100 pb-3">{t('uploadComponents.successStep.datasetSummary')}</h3>
             
             <div className="space-y-4 sm:space-y-6">
                <div>
                  <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">{t('uploadComponents.successStep.targetDataset')}</div>
                  <div className="text-base sm:text-lg font-bold text-slate-900 truncate flex items-center gap-2">
                    <Database className="w-4 h-4 text-blue-500" />
                    {datasetName}
                  </div>
                </div>

                <div>
                  <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">{t('uploadComponents.successStep.action')}</div>
                  <div className="text-xs sm:text-sm font-medium text-slate-700 bg-slate-50 inline-block px-3 py-1 rounded-md border border-slate-200">
                    {t('uploadComponents.successStep.metadataSplitUpdate')}
                  </div>
                </div>

                {splitUploadSuccess && (
                  <div>
                    <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">{t('uploadComponents.successStep.importResult')}</div>
                    <div className="text-xs sm:text-sm text-slate-600 bg-green-50/50 p-3 sm:p-4 rounded-xl border border-green-100 leading-relaxed text-wrap break-words">
                       {splitUploadSuccess}
                    </div>
                  </div>
                )}
             </div>
          </div>
        </div>
      </Card>
    </div>
  )
}
