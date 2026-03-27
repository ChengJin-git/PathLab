import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, MessageSquare, ListTodo, ActivitySquare } from 'lucide-react'

const STEP_DURATION = 3500

export function StickyWorkflowStory() {
  const { t } = useTranslation()
  const [activeStep, setActiveStep] = useState(0)
  const [progress, setProgress] = useState(0)
  const [paused, setPaused] = useState(false)
  const startRef = useRef(performance.now())
  const rafRef = useRef<number>(0)

  useEffect(() => {
    if (paused) return

    startRef.current = performance.now()

    const tick = (now: number) => {
      const elapsed = now - startRef.current
      const pct = Math.min(elapsed / STEP_DURATION, 1)
      setProgress(pct)
      if (pct >= 1) {
        setActiveStep((s) => (s + 1) % 3)
        startRef.current = now
        setProgress(0)
      }
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [paused])

  const jumpTo = (idx: number) => {
    setActiveStep(idx)
    setProgress(0)
    startRef.current = performance.now()
  }

  const steps = [
    {
      key: 'step1',
      titleKey: 'landing.story.step1.title',
      defaultTitle: '1. 告訴 AI 你的目標',
      descKey: 'landing.story.step1.desc',
      defaultDesc: '用日常語言描述你想在影像上執行的任務，告別繁冗表單。',
      icon: MessageSquare,
    },
    {
      key: 'step2',
      titleKey: 'landing.story.step2.title',
      defaultTitle: '2. 系統級自動配置',
      descKey: 'landing.story.step2.desc',
      defaultDesc: '引擎在幾秒內將你的意圖解析為底層的模型調用、環境分配和格式轉化指令。',
      icon: ListTodo,
    },
    {
      key: 'step3',
      titleKey: 'landing.story.step3.title',
      defaultTitle: '3. 監控進度與分析結果',
      descKey: 'landing.story.step3.desc',
      defaultDesc: '在一個控制台裡跟蹤執行進度，並可直接在數位切片中比對預測疊層模型。',
      icon: ActivitySquare,
    },
  ]

  return (
    <section className="relative bg-[#FDFDFD] py-12 sm:py-16 lg:py-24">
      <div
        role="none"
        className="max-w-7xl mx-auto px-4 sm:px-6"
        onMouseEnter={() => setPaused(true)}
        onTouchStart={() => setPaused(true)}
      >
        <div className="mb-8 sm:mb-12 lg:mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-[color:var(--landing-text-primary)] leading-tight">
            {t('landing.story.header', '只需三步，從靈感到可驗證的診斷證據')}
          </h2>
        </div>

        <div className="flex flex-col lg:flex-row gap-8 lg:gap-20 items-center">

          <div className="w-full lg:w-1/3 flex flex-col gap-6 lg:gap-8">
            {steps.map((step, idx) => {
              const Icon = step.icon
              const isActive = activeStep === idx
              return (
                <button
                  key={step.key}
                  type="button"
                  onClick={() => jumpTo(idx)}
                  className={`text-left transition-all duration-500 ${
                    isActive
                      ? 'opacity-100 scale-100'
                      : 'opacity-40 lg:scale-95 lg:origin-left hover:opacity-70 active:opacity-70'
                  }`}
                >
                  <div className="flex items-center gap-4 mb-3">
                    <div
                      className={`p-2.5 rounded-xl transition-colors duration-300 ${
                        isActive
                          ? 'bg-[color:var(--landing-primary)] text-white shadow-lg shadow-blue-500/30'
                          : 'bg-slate-100 text-slate-500'
                      }`}
                    >
                      <Icon className="w-5 h-5" />
                    </div>
                    <h3
                      className={`font-bold text-lg sm:text-xl transition-colors duration-300 ${
                        isActive
                          ? 'text-[color:var(--landing-text-primary)]'
                          : 'text-slate-500'
                      }`}
                    >
                      {t(step.titleKey, step.defaultTitle)}
                    </h3>
                  </div>
                  <p
                    className={`pl-[3.25rem] text-sm sm:text-base leading-relaxed transition-colors duration-300 ${
                      isActive
                        ? 'text-[color:var(--landing-text-secondary)]'
                        : 'text-slate-400'
                    }`}
                  >
                    {t(step.descKey, step.defaultDesc)}
                  </p>
                </button>
              )
            })}

            <div className="flex items-center gap-2 pl-[3.25rem] mt-2">
              {steps.map((step, idx) => (
                <button
                  key={step.key}
                  type="button"
                  onClick={() => jumpTo(idx)}
                  className="relative h-1 rounded-full overflow-hidden transition-all duration-300"
                  style={{
                    width: activeStep === idx ? 32 : 12,
                    background: 'var(--landing-border)',
                  }}
                >
                  {activeStep === idx && !paused && (
                    <span
                      className="absolute inset-y-0 left-0 rounded-full bg-[color:var(--landing-primary)]"
                      style={{ width: `${progress * 100}%` }}
                    />
                  )}
                  {activeStep === idx && paused && (
                    <span className="absolute inset-0 rounded-full bg-[color:var(--landing-primary)]" />
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="w-full lg:w-2/3 min-h-[340px] h-[60vw] max-h-[500px] lg:h-[70vh] lg:max-h-none relative">
            <div
              className={`absolute inset-0 flex items-center transition-all duration-700 ${
                activeStep === 0
                  ? 'opacity-100 translate-y-0 pointer-events-auto'
                  : 'opacity-0 translate-y-6 pointer-events-none'
              }`}
            >
              <div className="w-full rounded-[28px] bg-[#F7FBFD] border border-[color:var(--landing-border)] p-6 sm:p-10 shadow-sm ring-4 ring-[color:var(--landing-primary)]/5">
                <div className="w-full aspect-video bg-white rounded-2xl shadow-sm border border-[color:var(--landing-border)] flex flex-col justify-center px-6 sm:px-10 relative overflow-hidden">
                  <div className="absolute top-0 w-full h-1 bg-gradient-to-r from-blue-400 to-cyan-400 left-0" />
                  <p className="text-lg sm:text-xl font-mono text-slate-700 whitespace-pre-wrap">
                    {t('landing.story.step1.mock', '"Train a lymphocyte segmentation model on TCGA-BRCA dataset..."')}
                    <span className="animate-pulse text-blue-500">|</span>
                  </p>
                  <div className="mt-8 flex gap-3">
                    <span className="px-4 py-1.5 bg-blue-50 text-blue-600 rounded-full text-sm font-semibold border border-blue-100">{t('landing.story.step1.tag1', 'Segmentation')}</span>
                    <span className="px-4 py-1.5 bg-blue-50 text-blue-600 rounded-full text-sm font-semibold border border-blue-100">{t('landing.story.step1.tag2', 'Training')}</span>
                  </div>
                </div>
              </div>
            </div>

            <div
              className={`absolute inset-0 flex items-center transition-all duration-700 ${
                activeStep === 1
                  ? 'opacity-100 translate-y-0 pointer-events-auto'
                  : 'opacity-0 translate-y-6 pointer-events-none'
              }`}
            >
              <div className="w-full rounded-[28px] bg-[#F7FBFD] border border-[color:var(--landing-border)] p-6 sm:p-10 shadow-sm ring-4 ring-[color:var(--landing-primary)]/5">
                <div className="w-full aspect-video bg-white rounded-2xl shadow-sm border border-[color:var(--landing-border)] flex flex-col justify-center px-6 sm:px-10">
                  <div className="flex items-center justify-between mb-6 border-b border-[color:var(--landing-border)] pb-4">
                    <span className="font-semibold text-[color:var(--landing-text-primary)] text-lg">{t('landing.story.step2.mockTitle', 'System Configuration')}</span>
                    <CheckCircle2 className="w-6 h-6 text-emerald-500" />
                  </div>
                  <div className="space-y-4">
                    <div className="flex justify-between items-center bg-[#F1F7FB] p-4 rounded-xl border border-[color:var(--landing-border)]">
                      <span className="text-sm font-medium text-[color:var(--landing-text-secondary)]">{t('landing.story.step2.mockPipeline', 'Pipeline')}</span>
                      <span className="font-semibold text-[color:var(--landing-text-primary)]">{t('landing.story.step2.mockPipelineValue', 'Cell Segmentation')}</span>
                    </div>
                    <div className="flex justify-between items-center bg-[#F1F7FB] p-4 rounded-xl border border-[color:var(--landing-border)]">
                      <span className="text-sm font-medium text-[color:var(--landing-text-secondary)]">{t('landing.story.step2.mockModel', 'Model')}</span>
                      <span className="font-semibold text-[color:var(--landing-primary)]">SkinNet v1.2</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div
              className={`absolute inset-0 flex items-center transition-all duration-700 ${
                activeStep === 2
                  ? 'opacity-100 translate-y-0 pointer-events-auto'
                  : 'opacity-0 translate-y-6 pointer-events-none'
              }`}
            >
              <div className="w-full rounded-[28px] bg-[#F7FBFD] border border-[color:var(--landing-border)] p-6 sm:p-10 shadow-sm ring-4 ring-[color:var(--landing-primary)]/5">
                <div className="w-full aspect-video bg-white rounded-2xl shadow-sm border border-[color:var(--landing-border)] p-4 flex gap-4">
                  <div className="w-1/2 bg-slate-100 rounded-xl relative overflow-hidden border border-[color:var(--landing-border)]">
                    <img src="/images/mock-wsi.png" alt="WSI" className="absolute inset-0 w-full h-full object-cover opacity-90" />
                    <img src="/images/mock-heatmap.png" alt="Heatmap" className="absolute inset-0 w-full h-full object-cover mix-blend-screen opacity-80" />
                    <div className="absolute bottom-3 left-3 px-3 py-1 bg-white/90 backdrop-blur rounded shadow text-xs font-bold text-slate-700">
                      {t('landing.evidence.f1.title', 'Viewer')}
                    </div>
                  </div>
                  <div className="w-1/2 flex flex-col gap-3">
                    <div className="bg-[#F1F7FB] border border-[color:var(--landing-border)] rounded-xl p-4">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-semibold text-[color:var(--landing-text-secondary)]">{t('landing.story.step3.mockStatus', 'Task Status')}</span>
                        <span className="text-xs font-bold text-emerald-600">100%</span>
                      </div>
                      <div className="h-1.5 w-full bg-slate-200 rounded-full">
                        <div className="h-full bg-emerald-500 rounded-full w-full" />
                      </div>
                      <p className="text-xs text-[color:var(--landing-text-secondary)] mt-2">{t('landing.story.step3.mockCompleted', 'Completed')} · {t('landing.story.step3.mockDuration', '20m 34s')}</p>
                    </div>
                    <div className="flex-1 bg-[#F1F7FB] border border-[color:var(--landing-border)] rounded-xl p-4 flex flex-col justify-center">
                      <p className="text-xs font-semibold text-slate-500 mb-3">{t('landing.story.step3.mockPredTitle', 'Pred. Confidence')}</p>
                      <div className="flex flex-col gap-2.5">
                        <div className="flex items-center gap-2">
                           <span className="text-xs text-slate-500 w-20 shrink-0 leading-tight">{t('landing.story.step3.mockClass1', 'Tumor')}</span>
                           <div className="flex-1 bg-slate-200 h-1.5 rounded-full">
                             <div className="bg-[color:var(--landing-primary)] h-full rounded-full w-[87%]" />
                           </div>
                           <span className="text-xs font-bold text-slate-600 w-7 text-right">87%</span>
                         </div>
                         <div className="flex items-center gap-2">
                           <span className="text-xs text-slate-500 w-20 shrink-0 leading-tight">{t('landing.story.step3.mockClass2', 'Stroma')}</span>
                           <div className="flex-1 bg-slate-200 h-1.5 rounded-full">
                             <div className="bg-blue-300 h-full rounded-full w-[8%]" />
                           </div>
                           <span className="text-xs font-bold text-slate-600 w-7 text-right">8%</span>
                         </div>
                         <div className="flex items-center gap-2">
                           <span className="text-xs text-slate-500 w-20 shrink-0 leading-tight">{t('landing.story.step3.mockClass3', 'Necrosis')}</span>
                          <div className="flex-1 bg-slate-200 h-1.5 rounded-full">
                            <div className="bg-blue-200 h-full rounded-full w-[5%]" />
                          </div>
                          <span className="text-xs font-bold text-slate-600 w-7 text-right">5%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>
    </section>
  )
}
