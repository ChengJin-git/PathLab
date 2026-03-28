import { useTranslation } from 'react-i18next'
import { Zap } from 'lucide-react'
import { Button } from '../ui/button'
import { HeroPromptDemo } from './HeroPromptDemo'
import { HERO_DEMO_SCENARIO_EN, HERO_DEMO_SCENARIO_ZH, HERO_DEMO_SCENARIO_ZH_HK } from '../../constants/landing/landing-demo-content'

export function HeroSection({ onPrimaryCta }: { onPrimaryCta: () => void }) {
  const { t, i18n } = useTranslation()

  const isZh = i18n.language.startsWith('zh')
  let scenario = HERO_DEMO_SCENARIO_EN
  if (i18n.language === 'zh-HK') scenario = HERO_DEMO_SCENARIO_ZH_HK
  else if (isZh) scenario = HERO_DEMO_SCENARIO_ZH

  return (
    <section className="relative overflow-hidden pt-20 lg:pt-32 pb-12 lg:pb-24">
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute right-[-10%] top-0 w-[500px] h-[500px] bg-[#2f6bff]/5 rounded-full blur-[100px] opacity-70 translate-x-1/3 -translate-y-1/3" />
        <div className="absolute left-[-10%] bottom-[-10%] w-[400px] h-[400px] bg-[#14b8a6]/5 rounded-full blur-[100px] opacity-60 -translate-x-1/3 translate-y-1/3" />
      </div>

      <div className="mx-auto w-full max-w-7xl items-center grid gap-12 lg:gap-8 px-4 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] relative z-10 min-w-0">
        <div className="flex flex-col items-center lg:items-start text-center lg:text-left min-w-0">
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[#f1f7fb] border border-[#dce8f2] text-[color:var(--landing-primary)] text-xs font-bold uppercase tracking-wider mb-6 shadow-sm max-w-full">
            <Zap className="w-3.5 h-3.5 fill-[color:var(--landing-primary)]" />
            <span>{t('landing.hero.badge', 'Powered by Agentic AI')}</span>
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold leading-[1.15] tracking-tight mb-6 text-[color:var(--landing-text-primary)]">
            {t('landing.hero.title1', 'Master pathology')}
            <br />
            {!isZh && (
              <>{t('landing.hero.title1b', 'workflows with')}<br /></>
            )}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[color:var(--landing-primary)] to-cyan-500">
              {t('landing.hero.title2', 'natural language')}
            </span>
          </h1>

          <p className="text-[color:var(--landing-text-secondary)] text-lg leading-relaxed max-w-xl mx-auto lg:mx-0 mb-10">
            {t('landing.hero.subtitle', 'A true clinical-grade AI workspace. From data import and zero-shot configuration to log tracking and viewer evidence—all guided seamlessly by natural language.')}
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-4 w-full sm:w-auto">
            <Button
              onClick={onPrimaryCta}
              className="w-full sm:w-[200px] h-14 rounded-full text-base font-semibold shadow-xl shadow-blue-500/20 hover:-translate-y-0.5 bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] text-white"
            >
              {t('landing.hero.primaryCta', 'Get Started')}
            </Button>
            <Button
              onClick={() => window.location.href = 'mailto:jhc@ust.hk'}
              variant="outline"
              className="w-full sm:w-[200px] h-14 rounded-full text-base font-semibold border-[color:var(--landing-border)] text-[color:var(--landing-text-primary)] bg-white/50 backdrop-blur hover:bg-[#f1f7fb]"
            >
              {t('landing.hero.secondaryCta', 'Book Demo')}
            </Button>
          </div>

        </div>

        <div className="relative w-full z-20 max-w-xl mx-auto lg:max-w-none">
          <HeroPromptDemo key={i18n.language} scenario={scenario} />
        </div>
      </div>
    </section>
  )
}
