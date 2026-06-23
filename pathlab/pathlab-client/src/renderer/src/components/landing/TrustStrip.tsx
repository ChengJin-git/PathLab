import React from 'react'
import { useTranslation } from 'react-i18next'
import { MessageSquare, FileJson, Activity, BarChart4, Globe2 } from 'lucide-react'

export function TrustStrip() {
  const { t } = useTranslation()

  const trusts = [
    { icon: MessageSquare, key: 'landing.trustStrip.nlp', default: 'Natural Language Config' },
    { icon: FileJson, key: 'landing.trustStrip.formats', default: 'Multi-format Data Support' },
    { icon: Activity, key: 'landing.trustStrip.tracking', default: 'Task & Log Tracking' },
    { icon: BarChart4, key: 'landing.trustStrip.viz', default: 'Visual Results Analysis' },
    { icon: Globe2, key: 'landing.trustStrip.i18n', default: 'Multilingual Support' }
  ]

  return (
    <div className="w-full py-8 border-y border-[color:var(--landing-border)] bg-white/50 backdrop-blur-sm relative z-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col sm:flex-row sm:flex-wrap items-center justify-center gap-3 sm:gap-6">
          {trusts.map((item, idx) => {
            const Icon = item.icon
            return (
              <div 
                key={idx}
                className="flex items-center gap-2 px-4 py-2 bg-[color:var(--landing-surface)] border border-[color:var(--landing-border)] rounded-full shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-300 cursor-default"
              >
                <Icon className="w-4 h-4 text-[color:var(--landing-primary)]" />
                <span className="text-sm font-medium text-[color:var(--landing-text-secondary)]">
                  {t(item.key, item.default)}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
