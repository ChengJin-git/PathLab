import React from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../ui/button'
import { ArrowRight } from 'lucide-react'

export function FinalCTA({ onPrimaryCta }: { onPrimaryCta: () => void }) {
  const { t } = useTranslation()

  return (
    <section className="relative py-24 lg:py-32 overflow-hidden bg-gradient-to-br from-[#F7FBFD] to-[#E9F3FA]">
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -left-1/4 -bottom-1/4 w-[150%] h-[150%] bg-gradient-to-tr from-[color:var(--landing-soft-glow)] to-transparent rounded-[100%] blur-[120px] mix-blend-multiply opacity-60"></div>
      </div>
      
      <div className="relative max-w-4xl mx-auto px-4 sm:px-6 text-center z-10">
        <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-[color:var(--landing-text-primary)] tracking-tight mb-6">
          {t('landing.finalCta.title', 'Start your pathology AI workflow from the first natural language command')}
        </h2>
        <p className="text-lg text-[color:var(--landing-text-secondary)] mb-10 max-w-2xl mx-auto leading-relaxed">
          {t('landing.finalCta.subtitle', 'Leave the complex configuration to the system. Focus your time and effort on judgment, verification, and critical research.')}
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button 
            onClick={onPrimaryCta}
            className="h-14 px-8 rounded-full text-base bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] text-white shadow-lg shadow-blue-500/20 hover:shadow-xl hover:-translate-y-0.5 transition-all w-full sm:w-auto flex items-center gap-2"
          >
            {t('landing.finalCta.primary', 'Get Started Now')}
            <ArrowRight className="w-5 h-5" />
          </Button>
          <Button 
            onClick={() => window.location.href = 'mailto:jhc@ust.hk'}
            variant="outline"
            className="h-14 px-8 rounded-full text-base w-full sm:w-auto bg-white hover:bg-slate-50 border-[color:var(--landing-border)] text-[color:var(--landing-text-primary)]"
          >
            {t('landing.finalCta.secondary', 'Book a Demo')}
          </Button>
        </div>
      </div>
    </section>
  )
}
