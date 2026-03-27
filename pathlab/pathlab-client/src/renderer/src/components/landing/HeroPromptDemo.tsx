import React, { useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { useHeroDemoState } from '../../hooks/landing/useHeroDemoState'
import { HeroDemoScenario } from '../../types/landing'
import { Play } from 'lucide-react'

export function HeroPromptDemo({ scenario }: { scenario: HeroDemoScenario }) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const isInView = useInView(containerRef, { margin: '-100px' })
  
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

  return (
    <div ref={containerRef} className="relative w-full aspect-[4/3] rounded-[24px] bg-white border border-[color:var(--landing-border)] shadow-xl overflow-hidden flex flex-col">
       {/* Window Chrome */}
       <div className="flex items-center gap-2 px-4 py-3 border-b border-[color:var(--landing-border)] bg-[#FDFDFD]">
         <div className="w-3 h-3 rounded-full bg-rose-400"></div>
         <div className="w-3 h-3 rounded-full bg-amber-400"></div>
         <div className="w-3 h-3 rounded-full bg-emerald-400"></div>
         <div className="mx-auto text-xs font-medium text-[color:var(--landing-text-secondary)]">PathLab Workstation</div>
       </div>

       {/* Window Body */}
       <div className="flex-1 p-5 sm:p-6 flex flex-col gap-4 relative overflow-y-auto custom-scrollbar bg-[color:var(--landing-page-bg)]">
          {/* Typing Prompt */}
          <div className="bg-white rounded-xl p-4 shadow-sm border border-[color:var(--landing-border)] w-full relative">
            <span className="text-[color:var(--landing-text-primary)] font-medium leading-relaxed text-sm lg:text-base">
              {typedText}
              {phase === 'typing' && <span className="animate-pulse ml-1 text-[color:var(--landing-primary)]">|</span>}
            </span>
          </div>

          {/* Intent Summary */}
          {showIntent && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-wrap gap-2">
               {scenario.intent.map((field) => (
                 <div key={field.label} className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${field.emphasized ? 'bg-[#F1F7FB] border-blue-200 text-blue-700' : 'bg-white border-[color:var(--landing-border)] text-[color:var(--landing-text-secondary)]'}`}>
                   {field.label}: {field.value}
                 </div>
               ))}
            </motion.div>
          )}

          {/* Config Card */}
          {showConfig && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="bg-white border border-[color:var(--landing-border)] rounded-xl overflow-hidden shadow-sm">
               <div className="px-4 py-3 bg-[#F1F7FB] border-b border-[color:var(--landing-border)] flex items-center justify-between">
                 <span className="text-sm font-semibold text-[color:var(--landing-text-primary)]">{t('landing.mock.aiAutoConfig', 'AI Auto Configuration')}</span>
                  <span className="text-xs text-[color:var(--landing-primary)] bg-blue-100/50 px-2 py-0.5 rounded-md">{t('landing.mock.parsed', 'Parsed')}</span>
               </div>
               <div className="p-4 flex flex-col gap-3">
                 {scenario.config.map((item, idx) => (
                   <div key={item.label} className={`flex justify-between items-center text-xs sm:text-sm transition-opacity duration-300 ${idx < configVisibleCount ? 'opacity-100' : 'opacity-0 h-0 hidden'}`}>
                     <span className="text-[color:var(--landing-text-secondary)]">{item.label}</span>
                     <span className="font-medium text-[color:var(--landing-text-primary)]">{item.value}</span>
                   </div>
                 ))}
               </div>
            </motion.div>
          )}

          {/* Run Card / Results Card */}
          {(showRunCard || showResults) && (
            <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="transition-all duration-500">
               {showResults ? (
                 <div className="w-full bg-white rounded-xl shadow border border-emerald-500/30 overflow-hidden">
                    <div className="bg-emerald-50 px-4 py-2 border-b border-emerald-100 flex items-center justify-between">
                      <span className="text-emerald-700 text-xs font-semibold">{t('landing.mock.inferenceComplete', 'Inference Complete')}</span>
                       <button type="button" onClick={startRun} className="text-emerald-600 hover:text-emerald-800 text-xs bg-emerald-100/50 px-2 py-0.5 rounded transition">{t('landing.mock.restart', 'Restart')}</button>
                    </div>
                    <div className="p-4 flex gap-4">
                      <div className="w-1/2 aspect-video bg-slate-100 rounded-lg relative overflow-hidden border border-slate-200">
                         <img src="/images/mock-wsi.png" alt="result" className="w-full h-full object-cover" />
                         <img src="/images/mock-heatmap.png" alt="Heatmap overlay" className="absolute inset-0 mix-blend-screen opacity-80 w-full h-full object-cover" />
                         <div className="absolute bottom-2 left-2 bg-black/60 text-white text-[10px] px-2 py-0.5 rounded">{t('landing.mock.addHeatmap', '+Heatmap')}</div>
                      </div>
                      <div className="w-1/2 flex flex-col justify-end">
                        <div className="flex justify-between items-baseline mb-1">
                          <span className="text-xs text-slate-500 font-medium">{t('landing.mock.precision', 'Precision')}</span>
                          <span className="text-sm text-slate-800 font-bold">96.4%</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-1.5 mb-3 overflow-hidden"><div className="bg-emerald-400 h-1.5 w-[96.4%]"></div></div>
                        <div className="flex justify-between items-baseline mb-1">
                          <span className="text-xs text-slate-500 font-medium">{t('landing.mock.recall', 'Recall')}</span>
                          <span className="text-sm text-slate-800 font-bold">92.1%</span>
                        </div>
                        <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden"><div className="bg-emerald-400 h-1.5 w-[92.1%]"></div></div>
                      </div>
                    </div>
                 </div>
               ) : (
                  <button
                    type="button"
                    onClick={startRun}
                    disabled={!isReady}
                   className={`w-full py-3.5 rounded-xl flex items-center justify-center font-bold text-white transition-all shadow-md ${
                     isReady ? 'bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] cursor-pointer'
                     : phase === 'queueing' ? 'bg-amber-500 shadow-amber-500/20 cursor-wait'
                     : 'bg-emerald-500 shadow-emerald-500/20 cursor-default'
                   }`}
                 >
                   {isReady ? (
                     <><Play className="w-4 h-4 mr-2" fill="currentColor" /> {scenario.run.readyLabel}</>
                   ) : phase === 'queueing' ? (
                     scenario.run.queueingLabel
                   ) : (
                     scenario.run.runningLabel
                   )}
                 </button>
               )}
               {phase === 'running' && (
                 <div className="mt-4 w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                   <div className="bg-emerald-500 h-2 rounded-full transition-all duration-300 ease-out" style={{ width: `${progress}%` }}></div>
                 </div>
               )}
            </motion.div>
          )}
       </div>
    </div>
  )
}
