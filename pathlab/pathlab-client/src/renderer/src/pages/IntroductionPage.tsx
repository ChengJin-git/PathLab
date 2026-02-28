/**
 * PathLab Introduction / Landing Page
 */
import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTranslation } from 'react-i18next'
import { LanguageSwitcher } from '../components/common/LanguageSwitcher'
import {
  Microscope, Brain, Shield, Zap, ArrowRight, Upload,
  BarChart3, Sparkles, Heart, ExternalLink, ChevronDown, Check,
} from 'lucide-react'
import { motion, useInView } from 'framer-motion'
import { Button } from '../components/ui/button'
import { InstallPWA } from '../components/InstallPWA'

function FadeInSection({ children, className = '', delay = 0 }: {
  children: React.ReactNode; className?: string; delay?: number
}) {
  const ref = React.useRef<HTMLDivElement>(null)
  const isInView = useInView(ref, { once: true, margin: '-60px' })
  return (
    <motion.div ref={ref} initial={{ opacity: 0, y: 32 }}
      animate={isInView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.6, delay, ease: [0.22, 1, 0.36, 1] }}
      className={className}>{children}</motion.div>
  )
}

export default function IntroductionPage() {
  const navigate = useNavigate()
  const { isLoggedIn } = useAuth()
  React.useEffect(() => { if (isLoggedIn) navigate('/dashboard') }, [isLoggedIn, navigate])
  const goToLogin = () => navigate('/login')

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 overflow-x-hidden">
      <Navbar goToLogin={goToLogin} />
      <HeroSection />
      <FeaturesSection />
      <HowItWorksSection />
      <PricingSection goToLogin={goToLogin} />
      <Footer />
      <InstallPWA />
    </div>
  )
}

function Navbar({ goToLogin }: { goToLogin: () => void }) {
  const { t } = useTranslation()
  return (
    <nav className="sticky top-0 z-50 backdrop-blur-lg bg-white/80 border-b border-slate-200/60">
      <div className="max-w-6xl mx-auto flex items-center justify-between px-4 sm:px-6 h-14 sm:h-16">
        <img src="/images/pathlab-logo.png" alt="PathLab" className="h-7 sm:h-9 w-auto" />
        <div className="flex items-center gap-2 sm:gap-3">
          <LanguageSwitcher />
          <Button onClick={goToLogin}
            className="bg-slate-900 hover:bg-slate-800 text-white font-semibold px-4 sm:px-5 h-8 sm:h-9 text-sm sm:text-base rounded-full shadow-md">
            {t('introduction.signIn')}
          </Button>
        </div>
      </div>
    </nav>
  )
}

function HeroSection() {
  const { t } = useTranslation()
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute right-0 top-0 w-[300px] sm:w-[600px] h-[300px] sm:h-[600px] bg-blue-100 rounded-full blur-[80px] sm:blur-[120px] opacity-50 translate-x-1/3 -translate-y-1/3" />
        <div className="absolute left-0 bottom-0 w-[250px] sm:w-[500px] h-[250px] sm:h-[500px] bg-cyan-100 rounded-full blur-[80px] sm:blur-[120px] opacity-40 -translate-x-1/3 translate-y-1/3" />
      </div>
      <div className="relative max-w-6xl mx-auto px-4 sm:px-6 pt-16 sm:pt-24 pb-16 sm:pb-20 lg:pt-32 lg:pb-28 text-center">
        <FadeInSection>
          <div className="inline-flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-1.5 sm:py-2 rounded-full bg-blue-600 text-white shadow-lg shadow-blue-200 text-xs sm:text-sm font-bold uppercase tracking-wider mb-6 sm:mb-8">
            <Zap className="w-3 h-3 sm:w-4 sm:h-4 fill-current" /><span>{t('introduction.agenticAI')}</span>
          </div>
        </FadeInSection>
        <FadeInSection delay={0.1}>
          <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold leading-[1.1] sm:leading-[1.08] tracking-tight mb-4 sm:mb-6 px-2">
            {t('introduction.heroTitle1')}{t('introduction.heroTitle1') ? ' ' : ''}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-cyan-500">{t('introduction.heroTitle2')}</span>
            {t('introduction.heroTitle3') ? ' ' : ''}{t('introduction.heroTitle3')}
          </h1>
        </FadeInSection>
        <FadeInSection delay={0.2}>
          <p className="text-slate-600 text-base sm:text-lg md:text-xl leading-relaxed max-w-3xl mx-auto mb-8 sm:mb-10 px-4 break-keep">
            {t('introduction.heroSubtitle')}
          </p>
        </FadeInSection>
        <FadeInSection delay={0.3}>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4 px-4">
            <a href="#features" className="inline-block w-full sm:w-auto">
              <Button className="w-full sm:w-auto bg-slate-900 hover:bg-slate-800 text-white font-semibold px-6 sm:px-8 h-11 sm:h-12 rounded-full shadow-xl hover:shadow-2xl transition-all text-sm sm:text-base flex items-center justify-center gap-2">
                {t('introduction.learnMore')} <ChevronDown className="w-4 h-4" />
              </Button>
            </a>
          </div>
        </FadeInSection>
      </div>
    </section>
  )
}

function FeaturesSection() {
  const { t } = useTranslation()
  const features = [
    { icon: Microscope, title: t('introduction.features.wsiVisualization'), description: t('introduction.features.wsiVisualizationDesc') },
    { icon: Brain, title: t('introduction.features.aiAnalysis'), description: t('introduction.features.aiAnalysisDesc') },
    { icon: Shield, title: t('introduction.features.privacyFirst'), description: t('introduction.features.privacyFirstDesc') },
    { icon: Zap, title: t('introduction.features.smartAssistant'), description: t('introduction.features.smartAssistantDesc') },
  ]
  return (
    <section id="features" className="relative py-16 sm:py-24 lg:py-32">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <FadeInSection>
          <div className="text-center mb-12 sm:mb-16 px-4">
            <p className="text-blue-600 font-bold text-xs sm:text-sm uppercase tracking-wider mb-2 sm:mb-3">{t('introduction.coreCapabilities')}</p>
            <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight">{t('introduction.coreCapabilitiesTitle')}</h2>
          </div>
        </FadeInSection>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-5">
          {features.map((f, i) => {
            const Icon = f.icon
            return (
              <FadeInSection key={i} delay={i * 0.08}>
                <div className="bg-white border border-slate-200 rounded-2xl p-5 sm:p-6 h-full hover:border-blue-300 hover:shadow-lg hover:shadow-blue-500/5 transition-all duration-300 group">
                  <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-blue-50 flex items-center justify-center mb-3 sm:mb-4 group-hover:scale-110 transition-transform">
                    <Icon className="w-5 h-5 sm:w-6 sm:h-6 text-blue-600" />
                  </div>
                  <h3 className="text-slate-900 font-bold text-base sm:text-lg mb-1.5 sm:mb-2">{f.title}</h3>
                  <p className="text-slate-500 text-xs sm:text-sm leading-relaxed">{f.description}</p>
                </div>
              </FadeInSection>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function HowItWorksSection() {
  const { t } = useTranslation()
  const steps = [
    { icon: Upload, num: '01', title: t('introduction.steps.uploadSlides'), description: t('introduction.steps.uploadSlidesDesc') },
    { icon: Sparkles, num: '02', title: t('introduction.steps.aiAnalyzes'), description: t('introduction.steps.aiAnalyzesDesc') },
    { icon: BarChart3, num: '03', title: t('introduction.steps.getInsights'), description: t('introduction.steps.getInsightsDesc') },
  ]
  return (
    <section className="relative py-16 sm:py-24 lg:py-32 bg-white">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <FadeInSection>
          <div className="text-center mb-12 sm:mb-16 px-4">
            <p className="text-blue-600 font-bold text-xs sm:text-sm uppercase tracking-wider mb-2 sm:mb-3">{t('introduction.howItWorks')}</p>
            <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight">{t('introduction.howItWorksTitle')}</h2>
          </div>
        </FadeInSection>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-10 sm:gap-8 lg:gap-12">
          {steps.map((step, i) => {
            const Icon = step.icon
            return (
              <FadeInSection key={i} delay={i * 0.12}>
                <div className="text-center relative">
                  {i < steps.length - 1 && (
                    <div className="hidden md:block absolute top-10 left-[60%] w-[80%] border-t-2 border-dashed border-slate-200" />
                  )}
                  <div className="relative inline-flex items-center justify-center w-16 h-16 sm:w-20 sm:h-20 rounded-2xl bg-gradient-to-br from-blue-50 to-cyan-50 border border-slate-200 mb-4 sm:mb-6 shadow-sm">
                    <Icon className="w-7 h-7 sm:w-8 sm:h-8 text-blue-600" />
                    <span className="absolute -top-1.5 -right-1.5 sm:-top-2 sm:-right-2 w-6 h-6 sm:w-7 sm:h-7 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center shadow">
                      {step.num}
                    </span>
                  </div>
                  <h3 className="text-slate-900 font-bold text-base sm:text-lg mb-1.5 sm:mb-2">{step.title}</h3>
                  <p className="text-slate-500 text-xs sm:text-sm leading-relaxed max-w-xs mx-auto px-4">{step.description}</p>
                </div>
              </FadeInSection>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function PricingSection({ goToLogin }: { goToLogin: () => void }) {
  const { t } = useTranslation()
  const individualFeatures = [
    t('introduction.features.wsiVisualization'),
    t('introduction.features.aiAnalysis'),
    t('introduction.features.privacyFirstDesc'),
    t('introduction.features.smartAssistant'),
  ]
  const enterpriseFeatures = [
    t('introduction.enterpriseFeatures.customIntegrations'),
    t('introduction.enterpriseFeatures.prioritySupport'),
    t('introduction.enterpriseFeatures.ssoAccessControls'),
    t('introduction.enterpriseFeatures.enterpriseSecurity'),
    t('introduction.enterpriseFeatures.multiTenant'),
    t('introduction.enterpriseFeatures.dedicatedManager'),
  ]
  return (
    <section className="relative py-16 sm:py-24 lg:py-32">
      <div className="max-w-5xl mx-auto px-4 sm:px-6">
        <FadeInSection>
          <div className="text-center mb-12 sm:mb-16 px-4">
            <p className="text-blue-600 font-bold text-xs sm:text-sm uppercase tracking-wider mb-2 sm:mb-3">{t('introduction.pricing')}</p>
            <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight">{t('introduction.pricingTitle')}</h2>
          </div>
        </FadeInSection>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 sm:gap-6 lg:gap-8">
          {/* Individual / Free */}
          <FadeInSection delay={0.08}>
            <div className="bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 h-full flex flex-col hover:border-blue-300 hover:shadow-lg hover:shadow-blue-500/5 transition-all duration-300">
              <p className="text-blue-600 font-bold text-xs sm:text-sm uppercase tracking-wider mb-2">{t('introduction.individual')}</p>
              <div className="flex items-baseline gap-1 mb-2 sm:mb-3">
                <span className="text-3xl sm:text-4xl font-extrabold tracking-tight">{t('introduction.free')}</span>
              </div>
              <p className="text-slate-500 text-xs sm:text-sm leading-relaxed mb-5 sm:mb-6">
                {t('introduction.individualDesc')}
              </p>
              <ul className="space-y-2.5 sm:space-y-3 mb-6 sm:mb-8 flex-1">
                {individualFeatures.map((feat) => (
                  <li key={feat} className="flex items-start gap-2 sm:gap-2.5 text-xs sm:text-sm text-slate-700">
                    <Check className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                    <span>{feat}</span>
                  </li>
                ))}
              </ul>

              {/* Donation note */}
              <div className="bg-gradient-to-br from-slate-50 to-white rounded-xl p-3 sm:p-4 mb-4 sm:mb-5 border border-slate-100 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-20 h-20 bg-rose-100/30 rounded-full -mr-10 -mt-10 blur-xl" />
                <div className="relative z-10 flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-3">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <Heart className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-rose-500 fill-rose-500 animate-pulse flex-shrink-0" />
                    <p className="text-slate-700 text-xs font-semibold">{t('introduction.keepFree')}</p>
                  </div>
                  <a href="https://ko-fi.com/pathlab" target="_blank" rel="noopener noreferrer" className="w-full sm:w-auto flex-shrink-0">
                    <Button className="w-full sm:w-auto bg-slate-900 hover:bg-slate-800 text-white font-bold text-xs px-4 h-8 rounded-lg transition-all flex items-center justify-center gap-1.5">
                      {t('introduction.donate')} <ExternalLink className="w-3 h-3 opacity-70" />
                    </Button>
                  </a>
                </div>
              </div>

              <Button onClick={goToLogin}
                className="w-full bg-white hover:bg-slate-50 text-slate-900 font-semibold h-10 sm:h-11 text-sm sm:text-base rounded-xl border border-slate-300 hover:border-slate-400 transition-all flex items-center justify-center gap-2">
                {t('introduction.getStarted')} <ArrowRight className="w-4 h-4" />
              </Button>
            </div>
          </FadeInSection>

          {/* Enterprise / Custom */}
          <FadeInSection delay={0.16}>
            <div className="relative bg-gradient-to-br from-slate-900 to-slate-800 rounded-2xl p-6 sm:p-8 h-full flex flex-col overflow-hidden">
              <div className="absolute inset-0 pointer-events-none">
                <div className="absolute right-0 top-0 w-40 sm:w-56 h-40 sm:h-56 bg-blue-500/10 rounded-full blur-3xl translate-x-1/3 -translate-y-1/3" />
                <div className="absolute left-0 bottom-0 w-40 sm:w-56 h-40 sm:h-56 bg-cyan-500/10 rounded-full blur-3xl -translate-x-1/3 translate-y-1/3" />
              </div>
              <div className="relative z-10 flex flex-col h-full">
                <p className="text-blue-400 font-bold text-xs sm:text-sm uppercase tracking-wider mb-2">{t('introduction.enterprise')}</p>
                <div className="flex items-baseline gap-1 mb-2 sm:mb-3">
                  <span className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white">{t('introduction.custom')}</span>
                </div>
                <p className="text-slate-400 text-xs sm:text-sm leading-relaxed mb-5 sm:mb-6">
                  {t('introduction.enterpriseDesc')}
                </p>
                <ul className="space-y-2.5 sm:space-y-3 mb-6 sm:mb-8 flex-1">
                  {enterpriseFeatures.map((feat) => (
                    <li key={feat} className="flex items-start gap-2 sm:gap-2.5 text-xs sm:text-sm text-slate-300">
                      <Check className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-blue-400 mt-0.5 flex-shrink-0" />
                      <span>{feat}</span>
                    </li>
                  ))}
                </ul>
                <a href="mailto:jhc@ust.hk" className="block">
                  <Button className="w-full bg-white/10 hover:bg-white/20 text-white font-semibold h-10 sm:h-11 text-sm sm:text-base rounded-xl border border-white/20 hover:border-white/30 backdrop-blur transition-all flex items-center justify-center gap-2">
                    {t('introduction.contactTeam')} <ArrowRight className="w-4 h-4" />
                  </Button>
                </a>
              </div>
            </div>
          </FadeInSection>
        </div>
      </div>
    </section>
  )
}

function Footer() {
  const { t } = useTranslation()
  return (
    <footer className="border-t border-slate-200 bg-white py-8 sm:py-10">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3 sm:gap-4">
        <div className="flex items-center gap-3">
          <a
            href="https://smartlab.cse.ust.hk/" target="_blank" rel="noopener noreferrer"
            className="block opacity-80 hover:opacity-100 transition-opacity duration-300"
          >
            <img src="/images/smartlab-logo.svg" alt="SmartLab" className="h-10 sm:h-12 w-auto" />
          </a>
        </div>
        <p className="text-slate-400 text-xs text-center sm:text-left">© 2026 <a href="https://smartlab.cse.ust.hk/" target="_blank" rel="noopener noreferrer">SmartLab</a> · {t('introduction.allRightsReserved')}</p>
      </div>
    </footer>
  )
}
