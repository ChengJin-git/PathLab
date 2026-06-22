import { useTranslation } from 'react-i18next'
import { Zap } from 'lucide-react'
import { Button } from '../ui/button'
import { HeroPromptDemo } from './HeroPromptDemo'
import { HERO_DEMO_SCENARIO_EN, HERO_DEMO_SCENARIO_ZH, HERO_DEMO_SCENARIO_ZH_HK } from '../../constants/landing/landing-demo-content'
import { motion, useScroll, useTransform } from 'framer-motion'

export function HeroSection({ onPrimaryCta }: { onPrimaryCta: () => void }) {
  const { t, i18n } = useTranslation()

  const isZh = i18n.language.startsWith('zh')
  let scenario = HERO_DEMO_SCENARIO_EN
  if (i18n.language === 'zh-HK') scenario = HERO_DEMO_SCENARIO_ZH_HK
  else if (isZh) scenario = HERO_DEMO_SCENARIO_ZH

  const { scrollY } = useScroll()
  const isDesktop = typeof window !== 'undefined' && window.innerWidth >= 1024;
  const bg1Y = useTransform(scrollY, [0, 1000], isDesktop ? [0, 300] : [0, 0])
  const bg2Y = useTransform(scrollY, [0, 1000], isDesktop ? [0, -150] : [0, 0])

  return (
    <section className="relative overflow-hidden pb-12 pt-20 lg:pb-24 lg:pt-32">
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <motion.div style={{ y: bg1Y }} className="absolute right-[-10%] top-0 h-[540px] w-[540px] rounded-full bg-[#2f6bff]/8 blur-[120px] opacity-70 translate-x-1/3 -translate-y-1/3" />
        <motion.div style={{ y: bg2Y }} className="absolute bottom-[-10%] left-[-10%] h-[420px] w-[420px] rounded-full bg-[#764ba2]/7 blur-[120px] opacity-60 -translate-x-1/3 translate-y-1/3" />
      </div>

      <div className="mx-auto w-full max-w-7xl items-center grid gap-12 lg:gap-8 px-4 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] relative z-10 min-w-0">
        <div className="flex flex-col items-center lg:items-start text-center lg:text-left min-w-0">
          <div className="mb-6 inline-flex max-w-full items-center gap-1.5 rounded-full border border-white/70 bg-white/75 px-3 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-[color:var(--landing-primary)] shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur-xl">
            <Zap className="w-3.5 h-3.5 fill-[color:var(--landing-primary)]" />
            <span>{t('landing.hero.badge', 'Powered by Agentic AI')}</span>
          </div>

          <h1 className="mb-8 text-5xl font-semibold leading-[1.04] tracking-[-0.05em] text-[color:var(--landing-text-primary)] sm:text-6xl lg:text-[5.15rem]">
            {t('landing.hero.title1', 'Master pathology')}
            <br />
            {!isZh && (
              <>{t('landing.hero.title1b', 'workflows with')}<br /></>
            )}
            <span className="bg-gradient-to-r from-[color:var(--landing-primary)] via-[#4f7fff] to-secondary-400 bg-clip-text text-transparent">
              {t('landing.hero.title2', 'natural language')}
            </span>
          </h1>

          <p className="mb-10 mx-auto max-w-2xl text-lg font-medium leading-relaxed text-[color:var(--landing-text-secondary)] sm:text-xl lg:mx-0">
            {t('landing.hero.subtitle', 'A true clinical-grade AI workspace. From data import and zero-shot configuration to log tracking and viewer evidence—all guided seamlessly by natural language.')}
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-4 w-full sm:w-auto">
            <Button
              onClick={onPrimaryCta}
              className="h-14 w-full text-base font-semibold shadow-[0_24px_48px_rgba(47,107,255,0.22)] sm:w-[220px]"
            >
              {t('landing.hero.primaryCta', 'Get Started')}
            </Button>
            <Button
              onClick={() => window.location.href = 'mailto:jhc@ust.hk'}
              variant="outline"
              className="h-14 w-full border-white/70 bg-white/72 text-base font-semibold text-[color:var(--landing-text-primary)] backdrop-blur-xl sm:w-[220px]"
            >
              {t('landing.hero.secondaryCta', 'Book Demo')}
            </Button>
          </div>

        </div>

        <div className="relative z-20 mx-auto w-full max-w-xl lg:max-w-none">
          <div className="absolute inset-[-6%] rounded-[2rem] bg-gradient-to-br from-[color:var(--landing-soft-glow)] via-white/30 to-secondary-400/12 blur-3xl" />
          <div className="relative rounded-[2rem] border border-white/70 bg-white/58 p-3 shadow-[0_28px_80px_rgba(15,23,42,0.12)] backdrop-blur-2xl sm:p-4">
          <HeroPromptDemo key={i18n.language} scenario={scenario} />
          </div>
        </div>
      </div>
    </section>
  )
}
