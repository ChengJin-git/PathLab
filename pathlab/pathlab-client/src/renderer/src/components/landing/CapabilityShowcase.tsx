import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useInView, motion } from 'framer-motion'
import { CAPABILITY_CARDS_EN, CAPABILITY_CARDS_ZH, CAPABILITY_CARDS_ZH_HK } from '../../constants/landing/landing-demo-content'
import { Search, Bot, Database, BarChart, Settings, MousePointer2, GitBranch, Cpu } from 'lucide-react'

const GPU_NODES = Array.from({ length: 16 }, (_, i) => ({ id: `node-${i}`, active: i < 8 }))

export function CapabilityShowcase() {
  const { t, i18n } = useTranslation()
  const sectionRef = useRef<HTMLDivElement>(null)
  const isInView = useInView(sectionRef, { once: true, margin: '-15%' })
  const isZh = i18n.language.startsWith('zh')

  let cards = CAPABILITY_CARDS_EN
  if (i18n.language === 'zh-HK') cards = CAPABILITY_CARDS_ZH_HK
  else if (isZh) cards = CAPABILITY_CARDS_ZH

  return (
    <section id="capabilities" ref={sectionRef} className="py-12 sm:py-16 lg:py-24 bg-[#F7FBFD] border-y border-[color:var(--landing-border)]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        <div className="text-center mb-8 sm:mb-12 lg:mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-[color:var(--landing-text-primary)] mb-4">
            {t('landing.capabilities.title', 'A Complete AI Pathology Toolset')}
          </h2>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Main Card */}
          <div className="lg:col-span-8 bg-white rounded-[28px] border border-[color:var(--landing-border)] p-8 sm:p-12 group hover:shadow-xl hover:border-blue-200 transition-all duration-300 relative overflow-hidden flex flex-col shadow-sm">
            <div className="absolute top-0 right-0 w-64 h-64 bg-blue-50/50 rounded-full blur-3xl -translate-y-1/2 translate-x-1/3 group-hover:bg-blue-100/60 transition-colors"></div>

            <div className="relative z-10 flex-1">
              <div className="flex items-center gap-4 mb-6">
                <div className="p-3 bg-[color:var(--landing-primary)] rounded-2xl shadow-lg shadow-blue-500/20 text-white">
                  <Bot className="w-6 h-6" />
                </div>
                <h3 className="text-2xl font-bold text-[color:var(--landing-text-primary)]">
                  {t('landing.capabilities.main.title', 'Your Intelligent Research Copilot')}
                </h3>
              </div>

              <div className="w-full mt-8 bg-[#F8FAFC] rounded-2xl p-6 border border-[color:var(--landing-border)] relative">
                <div className="flex items-center bg-white border border-slate-200 rounded-full p-2 pl-4 pr-2 shadow-sm group-hover:shadow-md transition-shadow">
                  <Search className="w-5 h-5 text-slate-400 mr-2" />
                  <div className="flex-1 text-slate-400 text-sm">{t('landing.mock.searchPlaceholder', 'Ask about your active jobs...')}</div>
                  <div className="bg-[color:var(--landing-primary)] text-white p-2 rounded-full shadow-md"><MousePointer2 className="w-4 h-4" /></div>
                </div>
                <div className="mt-8 flex flex-col gap-3">
                  <div className={`flex bg-white p-3 rounded-xl border border-slate-100 shadow-sm transition-all items-center gap-3 ${isInView ? 'opacity-100 -translate-y-1' : 'opacity-80 group-hover:opacity-100 group-hover:-translate-y-1'}`}>
                    <div className="p-2 bg-blue-50 rounded-lg"><GitBranch className="w-5 h-5 text-blue-500" /></div>
                    <div className="flex-1">
                      <div className="flex justify-between items-center mb-1.5">
                        <span className="text-xs font-bold text-slate-700">{t('landing.mock.pipeline', 'Inference Pipeline')}</span>
                        <span className="text-[10px] font-semibold text-emerald-500 bg-emerald-50 px-1.5 py-0.5 rounded">{t('landing.mock.active', 'Active')}</span>
                      </div>
                      <div className="h-1.5 w-full bg-slate-100 rounded overflow-hidden">
                        <div className={`h-full bg-blue-400 transition-all duration-1000 ease-out delay-100 ${isInView ? 'w-[85%]' : 'w-1/3 group-hover:w-[85%]'}`}></div>
                      </div>
                    </div>
                  </div>
                  <div className={`flex bg-white p-3 rounded-xl border border-slate-100 shadow-sm transition-all items-center gap-3 ${isInView ? 'opacity-100 -translate-y-1' : 'opacity-80 group-hover:opacity-100 group-hover:-translate-y-1'}`}>
                    <div className="p-2 bg-slate-50 rounded-lg"><Database className="w-5 h-5 text-slate-400" /></div>
                    <div className="flex-1">
                      <div className="flex justify-between items-center mb-1.5">
                        <span className="text-xs font-bold text-slate-700">{t('landing.mock.extraction', 'Data Extraction')}</span>
                        <span className="text-[10px] font-semibold text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">{t('landing.mock.queued', 'Queued')}</span>
                      </div>
                      <div className="h-1.5 w-full bg-slate-100 rounded"></div>
                    </div>
                  </div>

                  <div className={`mt-2 pt-3 border-t border-slate-200/60 transition-opacity flex items-center gap-3 ${isInView ? 'opacity-100' : 'opacity-60 group-hover:opacity-100'}`}>
                    <div className="p-1.5 bg-indigo-50 rounded-lg"><Cpu className="w-4 h-4 text-indigo-400" /></div>
                    <div className="flex-1">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-[10px] font-bold text-slate-500">{t('landing.mock.gpuAllocation', 'GPU Allocation')}</span>
                        <span className="text-[10px] font-semibold text-indigo-500">8 / 16 Nodes</span>
                      </div>
                      <div className="flex gap-1 h-3">
                        {GPU_NODES.map((node) => (
                          <div key={node.id} className={`flex-1 rounded-sm ${node.active ? 'bg-indigo-400' : 'bg-slate-200'}`} style={{ opacity: node.active ? 1 : 0.5 }}></div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 3 Sub Cards */}
          <div className="lg:col-span-4 flex flex-col gap-6">
            <SubCard card={cards[0]} icon={Settings} type="progress" isVisible={isInView} />
            <SubCard card={cards[1]} icon={BarChart} type="bar" isVisible={isInView} />
            <SubCard card={cards[2]} icon={Database} type="tags" isVisible={isInView} />
          </div>
        </div>
      </div>
    </section>
  )
}

function SubCard({ card, icon: Icon, type, isVisible }: { card: any, icon: any, type: string, isVisible: boolean }) {
  return (
    <div className="flex-1 bg-white rounded-3xl border border-[color:var(--landing-border)] p-6 group hover:shadow-lg hover:border-blue-200 transition-all relative overflow-hidden shadow-sm flex flex-col justify-center">
      <div className={`absolute right-[-10px] top-[-10px] transition-all duration-500 origin-top-right ${isVisible ? 'opacity-[0.03] scale-100' : 'opacity-0 group-hover:opacity-[0.03] scale-75 group-hover:scale-100'}`}>
        <Icon className="w-40 h-40 text-[color:var(--landing-primary)]" />
      </div>
      <h4 className="font-bold text-lg text-[color:var(--landing-text-primary)] mb-2 relative z-10">{card?.title}</h4>
      <p className="text-sm text-[color:var(--landing-text-secondary)] relative z-10 leading-relaxed">{card?.description}</p>

      {type === 'progress' && (
        <div className="mt-5 flex flex-col gap-3 relative z-10 w-[90%]">
          <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div className={`h-full bg-[color:var(--landing-primary)] transition-all duration-1000 ease-out ${isVisible ? 'w-[92%]' : 'w-1/3 group-hover:w-[92%]'}`}></div>
          </div>
          <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden opacity-70">
            <div className={`h-full bg-[color:var(--landing-primary)] transition-all duration-1000 ease-out delay-75 ${isVisible ? 'w-[68%]' : 'w-1/4 group-hover:w-[68%]'}`}></div>
          </div>
          <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden opacity-40">
            <div className={`h-full bg-[color:var(--landing-primary)] transition-all duration-1000 ease-out delay-150 ${isVisible ? 'w-[35%]' : 'w-0 group-hover:w-[35%]'}`}></div>
          </div>
        </div>
      )}
      {type === 'bar' && (
        <div className="mt-8 flex justify-between items-end relative z-10 w-full gap-2">
          {/* Bar Chart */}
          <div className="flex gap-1.5 items-end h-12 pb-2">
            <div className="flex flex-col items-center gap-1">
              <span className={`text-[9px] font-bold text-emerald-600 transition-all duration-300 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1 group-hover:opacity-100 group-hover:translate-y-0'}`}>.96</span>
              <div className={`w-4 sm:w-5 bg-emerald-100 transition-all duration-500 rounded-t-sm ${isVisible ? 'h-10' : 'h-3 group-hover:h-10'}`}></div>
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className={`text-[9px] font-bold text-emerald-600 transition-all duration-300 delay-75 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1 group-hover:opacity-100 group-hover:translate-y-0'}`}>.92</span>
              <div className={`w-4 sm:w-5 bg-emerald-200 transition-all duration-500 delay-75 rounded-t-sm ${isVisible ? 'h-9' : 'h-4 group-hover:h-9'}`}></div>
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className={`text-[9px] font-bold text-emerald-700 transition-all duration-300 delay-150 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1 group-hover:opacity-100 group-hover:translate-y-0'}`}>.98</span>
              <div className={`w-4 sm:w-5 bg-emerald-400 transition-all duration-500 delay-150 rounded-t-sm ${isVisible ? 'h-12' : 'h-3.5 group-hover:h-12'}`}></div>
            </div>
          </div>

          {/* Confusion Matrix (Subtle) */}
          <div className={`grid grid-cols-2 gap-[1px] w-10 h-10 shrink-0 transition-opacity duration-300 rounded overflow-hidden shadow-sm mb-2 ${isVisible ? 'opacity-100' : 'opacity-60 group-hover:opacity-100'}`}>
            <div className="bg-emerald-400 flex items-center justify-center">
              <span className={`text-[8px] font-bold text-white transition-opacity duration-300 delay-100 ${isVisible ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>96</span>
            </div>
            <div className="bg-emerald-100 flex items-center justify-center">
              <span className={`text-[8px] font-bold text-emerald-800 transition-opacity duration-300 delay-100 ${isVisible ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>4</span>
            </div>
            <div className="bg-rose-100 flex items-center justify-center">
              <span className={`text-[8px] font-bold text-rose-800 transition-opacity duration-300 delay-100 ${isVisible ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>8</span>
            </div>
            <div className="bg-emerald-300 flex items-center justify-center">
              <span className={`text-[8px] font-bold text-white transition-opacity duration-300 delay-100 ${isVisible ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>92</span>
            </div>
          </div>

          {/* ROC / AUC Curve Mock */}
          <div className={`relative w-10 h-10 shrink-0 border-l border-b border-slate-200 mb-2 transition-opacity duration-300 ${isVisible ? 'opacity-100' : 'opacity-60 group-hover:opacity-100'}`}>
            <div className="absolute inset-0 border-t border-slate-300 border-dashed" style={{ transform: 'rotate(45deg)', transformOrigin: 'top left', width: '141%' }}></div>
            <svg className="absolute inset-0 w-full h-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <path d="M 0,100 Q 15,10 100,0" fill="none" stroke="currentColor" className="text-blue-500" strokeWidth="6" strokeLinecap="round" />
            </svg>
            <span className="absolute -bottom-4 left-1/2 -translate-x-1/2 text-[8px] font-bold text-slate-400">AUC</span>
          </div>

          {/* KM Survival Curve Mock */}
          <div className={`relative w-10 h-10 shrink-0 border-l border-b border-slate-200 mb-2 transition-opacity duration-300 ${isVisible ? 'opacity-100' : 'opacity-60 group-hover:opacity-100'}`}>
            <svg className="absolute inset-0 w-full h-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <path d="M 0,0 L 25,0 L 25,40 L 60,40 L 60,80 L 100,80" fill="none" stroke="currentColor" className="text-rose-400" strokeWidth="5" />
              <path d="M 0,0 L 40,0 L 40,20 L 75,20 L 75,30 L 100,30" fill="none" stroke="currentColor" className="text-emerald-400" strokeWidth="5" />
            </svg>
            <span className="absolute -bottom-4 left-1/2 -translate-x-1/2 text-[8px] font-bold text-slate-400">KM</span>
          </div>
        </div>
      )}
      {type === 'tags' && (
        <div className="mt-5 flex flex-wrap gap-2 relative z-10">
          {['SVS', 'NDPI', 'DICOM', 'MRXS', 'TIFF', 'QPTIFF'].map((fmt, i) => (
            <span key={fmt} className={`px-2.5 py-1 text-[10px] font-bold rounded-lg transition-colors duration-300 ${isVisible ? 'bg-[color:var(--landing-primary)] text-white' : 'bg-[#F1F7FB] text-[color:var(--landing-text-secondary)] group-hover:bg-[color:var(--landing-primary)] group-hover:text-white'}`} style={{ transitionDelay: `${i * 30}ms` }}>{fmt}</span>
          ))}
        </div>
      )}
    </div>
  )
}
