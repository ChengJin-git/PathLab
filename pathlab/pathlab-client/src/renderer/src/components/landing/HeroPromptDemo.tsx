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
    <div ref={containerRef} className="relative w-full aspect-[4/3] rounded-[24px] bg-white border border-[color:var(--landing-border)] shadow-xl overflow-hidden flex flex-col">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[color:var(--landing-border)] bg-[#FDFDFD]">
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
              <div className="flex flex-col gap-4 flex-1 justify-center">
                <div className="bg-white rounded-xl p-4 shadow-sm border border-[color:var(--landing-border)]">
                  <span className="text-[color:var(--landing-text-primary)] font-medium leading-relaxed text-sm lg:text-base">
                    {typedText}
                    {phase === 'typing' && <span className="animate-pulse ml-1 text-[color:var(--landing-primary)]">|</span>}
                  </span>
                </div>
                {showIntent && (
                  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-wrap gap-2">
                    {scenario.intent.map((field) => (
                      <div
                        key={field.label}
                        className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${field.emphasized ? 'bg-[#F1F7FB] border-blue-200 text-blue-700' : 'bg-white border-[color:var(--landing-border)] text-[color:var(--landing-text-secondary)]'}`}
                      >
                        {field.label}: {field.value}
                      </div>
                    ))}
                  </motion.div>
                )}
              </div>
            )}

            {viewKey === 'config' && (
              <div className="flex flex-col h-full">
                <div className="bg-white border border-[color:var(--landing-border)] rounded-xl overflow-hidden shadow-sm flex flex-col flex-1">
                  <div className="px-4 py-2.5 bg-[#F1F7FB] border-b border-[color:var(--landing-border)] flex items-center justify-between flex-shrink-0">
                    <span className="text-sm font-semibold text-[color:var(--landing-text-primary)]">{t('landing.mock.aiAutoConfig', 'AI Auto Configuration')}</span>
                    <span className="text-xs text-[color:var(--landing-primary)] bg-blue-100/50 px-2 py-0.5 rounded-md">{t('landing.mock.parsed', 'Parsed')}</span>
                  </div>
                  <div className="px-4 py-3 flex flex-col gap-2.5 flex-1">
                    {scenario.config.map((item, idx) => (
                      <div
                        key={item.label}
                        className={`flex justify-between items-center text-xs sm:text-sm transition-opacity duration-300 ${idx < configVisibleCount ? 'opacity-100' : 'opacity-0 h-0 hidden'}`}
                      >
                        <span className="text-[color:var(--landing-text-secondary)]">{item.label}</span>
                        <span className="font-medium text-[color:var(--landing-text-primary)]">{item.value}</span>
                      </div>
                    ))}
                  </div>
                  {showRunCard && (
                    <motion.div
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="px-4 pb-4 pt-3 flex-shrink-0 border-t border-[color:var(--landing-border)]"
                    >
                      <button
                        type="button"
                        onClick={startRun}
                        disabled={!isReady}
                        className={`w-full py-2.5 rounded-xl flex items-center justify-center font-bold text-white text-sm transition-all shadow-md ${
                          isReady
                            ? 'bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] cursor-pointer'
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
                        <div className="mt-2.5 w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                          <div className="bg-emerald-500 h-1.5 rounded-full transition-all duration-300 ease-out" style={{ width: `${progress}%` }} />
                        </div>
                      )}
                    </motion.div>
                  )}
                </div>
              </div>
            )}

            {viewKey === 'results' && (
              <div className="flex flex-col h-full">
                <div className="w-full bg-white rounded-xl shadow border border-emerald-500/30 overflow-hidden flex flex-col flex-1">
                  <div className="bg-emerald-50 px-4 py-2 border-b border-emerald-100 flex items-center justify-between flex-shrink-0">
                    <span className="text-emerald-700 text-xs font-semibold">{t('landing.mock.inferenceComplete', 'Inference Complete')}</span>
                    <button type="button" onClick={startRun} className="text-emerald-600 hover:text-emerald-800 text-xs bg-emerald-100/50 px-2 py-0.5 rounded transition cursor-pointer">
                      {t('landing.mock.restart', 'Restart')}
                    </button>
                  </div>
                  <div className="p-4 flex gap-4 flex-1">
                    <div className="w-1/2 bg-slate-100 rounded-lg relative overflow-hidden border border-slate-200 flex-shrink-0">
                      <img src="/images/mock-wsi.png" alt="result" className="w-full h-full object-cover" />
                      <div className={`absolute inset-0 transition-opacity duration-500 ${heatmapVisible ? 'opacity-100' : 'opacity-0'}`}>
                        <img src="/images/mock-heatmap.png" alt="Heatmap overlay" className="mix-blend-screen opacity-80 w-full h-full object-cover" />
                      </div>
                      <button
                        type="button"
                        onClick={() => setHeatmapVisible(v => !v)}
                        className={`absolute bottom-2 left-2 text-white text-[10px] px-2 py-0.5 rounded transition-all duration-200 cursor-pointer select-none ${
                          heatmapVisible
                            ? 'bg-emerald-600/80 hover:bg-emerald-700/90 ring-1 ring-emerald-400/60'
                            : 'bg-black/60 hover:bg-black/80'
                        }`}
                      >
                        {heatmapVisible ? t('landing.mock.hideHeatmap', '−热度图') : t('landing.mock.addHeatmap', '+热度图')}
                      </button>
                    </div>
                    <div className="flex-1 flex flex-col justify-between py-0.5 min-w-0">
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
