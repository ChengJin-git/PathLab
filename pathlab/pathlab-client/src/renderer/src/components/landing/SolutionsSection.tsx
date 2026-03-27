import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { SOLUTIONS_TABS } from '../../constants/landing/landing-solutions'
import { SolutionTabKey } from '../../types/landing'
import { CheckCircle2 } from 'lucide-react'

export function SolutionsSection() {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<SolutionTabKey>('clinician')

  const activeContent = SOLUTIONS_TABS.find(tab => tab.key === activeTab)

  return (
    <section id="solutions" className="py-12 sm:py-16 lg:py-24 bg-white">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="text-center mb-8 sm:mb-12 lg:mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-[color:var(--landing-text-primary)] mb-4">
            {t('landing.solutions.title', 'Built for every role in pathology')}
          </h2>
        </div>

        <div className="flex flex-col lg:flex-row gap-6 lg:gap-16 items-start max-w-5xl mx-auto">
          <div className="w-full lg:w-[240px] grid grid-cols-3 lg:flex lg:flex-col gap-2 lg:gap-3 shrink-0">
            {SOLUTIONS_TABS.map(tab => {
              const Icon = tab.icon
              const isActive = activeTab === tab.key
              return (
                <button
                  type="button"
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex flex-col lg:flex-row items-center lg:items-center gap-1.5 lg:gap-3 text-center lg:text-left px-3 lg:px-5 py-3 lg:py-4 rounded-xl transition-all group ${
                    isActive
                      ? 'bg-white shadow-md border border-[color:var(--landing-primary)]/20 text-[color:var(--landing-primary)]'
                      : 'text-[color:var(--landing-text-secondary)] hover:bg-[#f7fbfd] border border-transparent hover:border-[color:var(--landing-border)]'
                  }`}
                >
                  <Icon className={`w-5 h-5 shrink-0 transition-colors ${isActive ? 'text-[color:var(--landing-primary)]' : 'text-slate-400 group-hover:text-[color:var(--landing-primary)]'}`} />
                  <span className="font-bold text-xs lg:text-[15px] leading-tight">{t(tab.labelKey, tab.key)}</span>
                </button>
              )
            })}
          </div>

          <div className="w-full flex-1 bg-white border border-[color:var(--landing-border)] rounded-[28px] p-6 sm:p-8 lg:p-12 shadow-[0_8px_30px_rgb(0,0,0,0.04)] lg:min-h-[320px] transition-all relative overflow-hidden">
            <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-br from-[color:var(--landing-primary)]/5 to-transparent rounded-bl-full pointer-events-none"></div>
            {activeContent && (
              <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                <h3 className="text-xl sm:text-2xl font-bold text-[color:var(--landing-text-primary)] mb-3 sm:mb-4">
                  {t(activeContent.labelKey, activeContent.key)}
                </h3>
                <p className="text-base sm:text-lg text-[color:var(--landing-text-secondary)] mb-6 sm:mb-8">
                  {t(activeContent.descKey, 'Empowering your workflow with intelligent assistance.')}
                </p>
                <div className="grid sm:grid-cols-2 gap-3 sm:gap-4">
                  {activeContent.bulletKeys.map((bullet) => (
                    <div key={bullet} className="flex items-start gap-3">
                      <CheckCircle2 className="w-5 h-5 text-[color:var(--landing-accent)] shrink-0 mt-0.5" />
                      <span className="text-sm sm:text-base text-[color:var(--landing-text-primary)]">{t(bullet, bullet)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
