import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useInView } from 'framer-motion'
import { Layers, CheckCircle2, Eye, EyeOff } from 'lucide-react'

export function EvidenceLayer() {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  const isInView = useInView(ref, { margin: '-20%' })
  const [heatmapOn, setHeatmapOn] = useState(true)

  const showHeatmap = isInView && heatmapOn

  return (
    <section className="py-12 sm:py-16 lg:py-24 bg-white border-b border-[color:var(--landing-border)] overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        <div className="flex flex-col-reverse lg:flex-row gap-12 lg:gap-16 items-center">
          
          <div ref={ref} className="w-full lg:w-3/5">
             <div className="w-full aspect-[4/3] bg-slate-900 rounded-[28px] overflow-hidden shadow-2xl relative border border-slate-800">
               
               {/* Base WSI Image */}
               <img src="/images/mock-wsi.png" alt="WSI Background" className="absolute inset-0 w-full h-full object-cover opacity-90" />
               
               {/* Sliding Heatmap Overlay Image */}
               <img src="/images/mock-heatmap.png" alt="Heatmap Overlay"
                 className="absolute inset-0 w-full h-full object-cover mix-blend-screen transition-all duration-[2000ms] ease-out min-w-full"
                 style={{ 
                   opacity: showHeatmap ? 0.9 : 0, 
                   clipPath: showHeatmap ? 'polygon(0 0, 100% 0, 100% 100%, 0 100%)' : 'polygon(0 0, 0 0, 0 100%, 0 100%)',
                   transform: `scale(${showHeatmap ? 1 : 1.1})` 
                 }}
               />
               
               {/* Scanner Line Effect */}
               <div 
                 className="absolute top-0 bottom-0 w-1 bg-blue-500 shadow-[0_0_15px_5px_rgba(59,130,246,0.5)] transition-all duration-[3000ms] ease-out z-10"
                 style={{ left: showHeatmap ? '100%' : '0%', opacity: showHeatmap ? 0.8 : 0 }}
               ></div>

               {/* Toggle Heatmap Button */}
               <div className="absolute top-5 right-5 flex flex-col gap-2 z-20">
                 <button
                   type="button"
                   onClick={() => setHeatmapOn(prev => !prev)}
                   className={`w-10 h-10 backdrop-blur-md rounded-xl flex items-center justify-center cursor-pointer border shadow-lg transition-all ${
                     heatmapOn
                       ? 'bg-blue-500/60 border-blue-400/40 text-white'
                       : 'bg-black/40 border-white/10 text-white/70 hover:text-white'
                   }`}
                   title={heatmapOn ? 'Hide Heatmap' : 'Show Heatmap'}
                 >
                   {heatmapOn ? <Eye className="w-5 h-5" /> : <EyeOff className="w-5 h-5" />}
                 </button>
                 <div className="w-10 h-10 bg-black/40 backdrop-blur-md rounded-xl flex items-center justify-center text-white/70 border border-white/10 shadow-lg">
                   <Layers className="w-5 h-5" />
                 </div>
               </div>

               <div className="absolute bottom-4 sm:bottom-8 left-4 sm:left-8 w-[calc(100%-2rem)] sm:w-60 lg:w-72 h-12 bg-black/50 backdrop-blur-xl rounded-full border border-white/10 flex items-center px-4 gap-4 shadow-xl z-20">
                 <span className="text-white/60 text-xs font-bold tracking-wider uppercase">{t('landing.mock.heatmapAlpha', 'Heatmap Alpha')}</span>
                 <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
                   <div 
                     className="h-full bg-[color:var(--landing-primary)] rounded-full transition-all duration-1000 delay-300"
                     style={{ width: showHeatmap ? '100%' : '0%' }}
                   ></div>
                 </div>
               </div>

               <div 
                 className="absolute hidden sm:block bottom-4 sm:bottom-8 right-4 sm:right-8 w-44 sm:w-56 bg-black/60 backdrop-blur-xl rounded-2xl border border-white/10 p-4 transition-all duration-700 delay-500 shadow-xl z-20"
                 style={{ opacity: showHeatmap ? 1 : 0, transform: `translateY(${showHeatmap ? 0 : 20}px)` }}
               >
                 <div className="text-xs text-emerald-400 font-bold mb-1.5">{t('landing.mock.analysisComplete', 'Analysis Complete')}</div>
                 <div className="text-[10px] sm:text-xs text-white/80 leading-relaxed font-medium">
                   {t('landing.mock.analysisDesc', 'High density region identified. Confidence score: 0.94.')}
                 </div>
               </div>
             </div>
          </div>

          <div className="w-full lg:w-2/5 flex flex-col justify-center">
            <h2 className="text-3xl sm:text-4xl font-bold text-[color:var(--landing-text-primary)] mb-6 leading-tight">
              {t('landing.evidence.title', 'Deep visual evidence, right in your workspace')}
            </h2>
            <p className="text-lg text-[color:var(--landing-text-secondary)] mb-10 leading-relaxed">
              {t('landing.evidence.desc', 'Stop switching between disjointed tools. View your pipeline results alongside the original Whole Slide Images, with synchronized heatmaps and opacity controls.')}
            </p>
            
            <ul className="space-y-6">
              <li className="flex items-start gap-4">
                <div className="p-1.5 rounded-full bg-blue-50 mt-1 border border-blue-100"><CheckCircle2 className="w-5 h-5 text-[color:var(--landing-primary)]" /></div>
                <div>
                  <h4 className="font-bold text-[color:var(--landing-text-primary)] text-lg mb-1">{t('landing.evidence.f1.title', 'Zero-latency visualization')}</h4>
                  <p className="text-sm text-[color:var(--landing-text-secondary)] leading-relaxed">{t('landing.evidence.f1.desc', 'Deep zoom into gigapixel tissue arrays instantly via the WebGL renderer.')}</p>
                </div>
              </li>
              <li className="flex items-start gap-4">
                <div className="p-1.5 rounded-full bg-blue-50 mt-1 border border-blue-100"><CheckCircle2 className="w-5 h-5 text-[color:var(--landing-primary)]" /></div>
                <div>
                  <h4 className="font-bold text-[color:var(--landing-text-primary)] text-lg mb-1">{t('landing.evidence.f2.title', 'Synchronized Overlays')}</h4>
                  <p className="text-sm text-[color:var(--landing-text-secondary)] leading-relaxed">{t('landing.evidence.f2.desc', 'Overlay AI inference results accurately onto the tissue source.')}</p>
                </div>
              </li>
            </ul>
          </div>

        </div>
      </div>
    </section>
  )
}
