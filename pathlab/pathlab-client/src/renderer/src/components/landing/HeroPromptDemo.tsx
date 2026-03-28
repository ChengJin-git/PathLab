import React, { useRef, useState, useEffect } from 'react'
import { motion, useInView, AnimatePresence } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { useHeroDemoState } from '../../hooks/landing/useHeroDemoState'
import { HeroDemoScenario } from '../../types/landing'
import { Play } from 'lucide-react'

export function HeroPromptDemo({ scenario }: { scenario: HeroDemoScenario }) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const isInView = useInView(containerRef, { margin: '-100px' })
  const [heatmapVisible, setHeatmapVisible] = useState(true)

  const {
    phase,
    typedText,
    configVisibleCount,
    progress,
    startRun,
    isReady,
    showIntent,
    showConfig,
    showRunCard,
    showResults
  } = useHeroDemoState({
    promptText: scenario.prompt,
    configItemCount: scenario.config.length,
    isInView,
    progressTarget: scenario.run.progressTarget
  })

  useEffect(() => {
    if (showResults) setHeatmapVisible(true)
  }, [showResults])

  const viewKey = showResults ? 'results' : showConfig ? 'config' : 'input'

  return (
    <div ref={containerRef} className="relative w-full h-[460px] sm:h-auto sm:aspect-[16/11] lg:aspect-[16/10] rounded-[24px] bg-white border border-[color:var(--landing-border)] shadow-2xl shadow-[color:var(--landing-primary)]/5 overflow-hidden flex flex-col sm:min-h-[380px]">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[color:var(--landing-border)] bg-[#FDFDFD] flex-shrink-0">
        <div className="w-3 h-3 rounded-full bg-rose-400" />
        <div className="w-3 h-3 rounded-full bg-amber-400" />
        <div className="w-3 h-3 rounded-full bg-emerald-400" />
        <div className="mx-auto text-xs font-medium text-[color:var(--landing-text-secondary)]">PathLab Workstation</div>
      </div>

      <div className="flex-1 relative overflow-hidden bg-[color:var(--landing-page-bg)]">
        <AnimatePresence mode="wait">
          <motion.div
            key={viewKey}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="absolute inset-0 p-5 sm:p-6 flex flex-col"
          >
            {viewKey === 'input' && (
              <div className="flex flex-col gap-6 h-full justify-center items-center w-full max-w-[640px] mx-auto text-center">
                <div className="w-full bg-white rounded-2xl p-6 shadow-sm border border-[color:var(--landing-border)] relative text-left">
                  <span className="text-[color:var(--landing-text-primary)] font-medium leading-relaxed text-[15px] sm:text-base">
                    {typedText}
                    {phase === 'typing' && <span className="animate-pulse ml-1 text-[color:var(--landing-primary)]">|</span>}
                  </span>
                </div>
                {showIntent && (
                  <motion.div initial={{ opacity: 0, scale: 0.95, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="flex flex-wrap sm:flex-nowrap justify-center gap-2 sm:gap-2.5 w-full">
                    {scenario.intent.map((field) => (
                      <div
                        key={field.label}
                        className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-colors whitespace-nowrap max-w-full truncate ${field.emphasized ? 'bg-[#F1F7FB] border-blue-200 text-blue-700 shadow-sm' : 'bg-white border-[color:var(--landing-border)] text-[color:var(--landing-text-secondary)]'}`}
                      >
                        {field.label}: {field.value}
                      </div>
                    ))}
                  </motion.div>
                )}
              </div>
            )}

            {viewKey === 'config' && (
              <div className="flex flex-col h-full items-center justify-center">
                <div className="w-full max-w-sm bg-white border border-[color:var(--landing-border)] rounded-2xl overflow-hidden shadow-lg flex flex-col">
                  <div className="px-5 py-3.5 bg-[#F1F7FB] border-b border-[color:var(--landing-border)] flex items-center justify-between gap-2">
                    <span className="text-[15px] font-bold text-[color:var(--landing-text-primary)] truncate flex-1" title={t('landing.mock.aiAutoConfig', 'AI Auto Configuration')}>{t('landing.mock.aiAutoConfig', 'AI Auto Configuration')}</span>
                    <span className="text-xs font-medium text-[color:var(--landing-primary)] bg-blue-100/60 px-2 py-0.5 rounded-md flex-shrink-0 whitespace-nowrap">{t('landing.mock.parsed', 'Parsed')}</span>
                  </div>
                  <div className="px-5 py-4 flex flex-col gap-3.5">
                    {scenario.config.map((item, idx) => (
                      <div
                        key={item.label}
                        className={`flex items-center gap-2 text-sm w-full transition-all duration-300 ${idx < configVisibleCount ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2 h-0 overflow-hidden'}`}
                      >
                        <span className="text-[color:var(--landing-text-secondary)] whitespace-nowrap flex-shrink-0">{item.label}</span>
                        <span className="font-semibold text-[color:var(--landing-text-primary)] truncate text-right min-w-0 flex-1" title={item.value}>{item.value}</span>
                      </div>
                    ))}
                  </div>
                  {showRunCard && (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="px-5 pb-5 pt-2"
                    >
                      <button
                        type="button"
                        onClick={startRun}
                        disabled={!isReady}
                        className={`w-full py-3 rounded-xl flex items-center justify-center font-bold text-white text-sm transition-all shadow-md ${
                          isReady
                            ? 'bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] cursor-pointer hover:shadow-lg hover:-translate-y-0.5'
                            : phase === 'queueing'
                            ? 'bg-amber-500 shadow-amber-500/20 cursor-wait'
                            : 'bg-emerald-500 shadow-emerald-500/20 cursor-default'
                        }`}
                      >
                        {isReady ? (
                          <><Play className="w-4 h-4 mr-2" fill="currentColor" />{scenario.run.readyLabel}</>
                        ) : phase === 'queueing' ? (
                          scenario.run.queueingLabel
                        ) : (
                          scenario.run.runningLabel
                        )}
                      </button>
                      {phase === 'running' && (
                        <div className="mt-3 w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                          <div className="bg-emerald-500 h-1.5 rounded-full transition-all duration-300 ease-out" style={{ width: `${progress}%` }} />
                        </div>
                      )}
                    </motion.div>
                  )}
                </div>
              </div>
            )}

            {viewKey === 'results' && (
              <div className="flex flex-col h-full items-center justify-center">
                <div className="w-full max-w-[500px] bg-white rounded-2xl shadow-lg border border-emerald-500/20 overflow-hidden flex flex-col">
                  <div className="bg-emerald-50/80 px-4 py-3 border-b border-emerald-100/80 flex items-center justify-between gap-2 min-w-0">
                    <span className="text-emerald-700 text-sm font-bold truncate flex-1">{t('landing.mock.inferenceComplete', 'Inference Complete')}</span>
                    <button type="button" onClick={startRun} className="text-emerald-600 flex-shrink-0 hover:text-emerald-800 text-xs font-semibold bg-emerald-100/50 hover:bg-emerald-200/50 px-2.5 py-1 rounded transition cursor-pointer whitespace-nowrap">
                      {t('landing.mock.restart', 'Restart')}
                    </button>
                  </div>
                  <div className="p-4 sm:p-5 flex flex-col sm:flex-row gap-4 sm:gap-6 overflow-y-auto">
                    <div className="w-full sm:w-[45%] h-[160px] sm:h-auto bg-slate-100 rounded-xl relative overflow-hidden border border-slate-200 flex-shrink-0 group">
                      <img src="/images/mock-wsi.png" alt="result" className="w-full h-full object-cover" />
                      {heatmapVisible && (
                        <div className="absolute inset-0">
                          <img src="/images/mock-heatmap.png" alt="Heatmap overlay" className="mix-blend-screen opacity-85 w-full h-full object-cover" />
                        </div>
                      )}
                      <button
                        type="button"
                        onClick={() => setHeatmapVisible(v => !v)}
                        className={`absolute bottom-2 left-2 text-white text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors cursor-pointer select-none shadow-sm ${
                          heatmapVisible
                            ? 'bg-emerald-600 hover:bg-emerald-700 ring-1 ring-emerald-400'
                            : 'bg-slate-900/70 hover:bg-slate-900'
                        }`}
                      >
                        {heatmapVisible ? t('landing.mock.hideHeatmap', '−热度图') : t('landing.mock.addHeatmap', '+热度图')}
                      </button>
                    </div>
                    <div className="flex-1 flex flex-col justify-between py-1 min-w-0 gap-3 sm:gap-0">
                      <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
                        {t('landing.mock.modelMetrics', 'Model Metrics')}
                      </p>
                      <div>
                        <div className="flex justify-between items-baseline mb-1">
                          <span className="text-xs text-slate-500 font-medium">{t('landing.mock.precision', 'Precision')}</span>
                          <span className="text-sm text-slate-800 font-bold">96.4%</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                          <div className="bg-emerald-400 h-1.5 rounded-full" style={{ width: '96.4%' }} />
                        </div>
                      </div>
                      <div>
                        <div className="flex justify-between items-baseline mb-1">
                          <span className="text-xs text-slate-500 font-medium">{t('landing.mock.recall', 'Recall')}</span>
                          <span className="text-sm text-slate-800 font-bold">92.1%</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                          <div className="bg-emerald-400 h-1.5 rounded-full" style={{ width: '92.1%' }} />
                        </div>
                      </div>
                      <div>
                        <div className="flex justify-between items-baseline mb-1">
                          <span className="text-xs text-slate-500 font-medium">F1 {t('landing.mock.score', 'Score')}</span>
                          <span className="text-sm text-slate-800 font-bold">94.2%</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                          <div className="bg-emerald-400 h-1.5 rounded-full" style={{ width: '94.2%' }} />
                        </div>
                      </div>
                      <div className="pt-1.5 border-t border-slate-100 flex items-center justify-between">
                        <span className="text-[9px] sm:text-[10px] text-slate-400">AUC-ROC</span>
                        <span className="text-xs font-bold text-emerald-600">0.977</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}
