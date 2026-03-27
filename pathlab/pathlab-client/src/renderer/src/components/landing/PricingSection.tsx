import { useTranslation } from 'react-i18next'
import { Check, Heart, ExternalLink, ArrowRight } from 'lucide-react'
import { PRICING_TIERS } from '../../constants/landing/landing-pricing'
import { Button } from '../ui/button'

export function PricingSection({ onPrimaryCta }: { onPrimaryCta: () => void }) {
  const { t } = useTranslation()

  return (
    <section id="pricing" className="relative py-12 sm:py-20 lg:py-32 bg-[color:var(--landing-page-bg)]">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 z-10 relative">
        <div className="text-center mb-8 sm:mb-12 lg:mb-16">
          <p className="text-[color:var(--landing-primary)] font-bold text-sm uppercase tracking-wider mb-3">
            {t('landing.nav.pricing', 'Pricing')}
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold text-[color:var(--landing-text-primary)] tracking-tight">
            {t('landing.pricing.title', 'Simple, transparent pricing')}
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 lg:gap-8">
          {/* Individual */}
          <div className="bg-white border border-[color:var(--landing-border)] rounded-[28px] p-8 h-full flex flex-col hover:border-blue-300 hover:shadow-xl transition-all duration-300">
            <p className="text-[color:var(--landing-primary)] font-bold text-sm uppercase tracking-wider mb-2">
              {t(PRICING_TIERS.individual.titleKey, 'Individual')}
            </p>
            <div className="flex items-baseline gap-1 mb-3">
              <span className="text-4xl font-extrabold tracking-tight text-[color:var(--landing-text-primary)]">
                {t(PRICING_TIERS.individual.priceKey, 'Free')}
              </span>
            </div>
            <p className="text-[color:var(--landing-text-secondary)] text-sm leading-relaxed mb-6">
              {t(PRICING_TIERS.individual.descKey, 'Suitable for clinical researchers.')}
            </p>
            <ul className="space-y-3 mb-8 flex-1">
              {PRICING_TIERS.individual.featuresKeys.map((featKey) => (
                <li key={featKey} className="flex items-start gap-3 text-sm text-slate-700">
                  <Check className="w-4 h-4 text-[color:var(--landing-primary)] mt-0.5 flex-shrink-0" />
                  <span>{t(featKey, featKey)}</span>
                </li>
              ))}
            </ul>

            <div className="bg-[#F1F7FB] rounded-2xl p-4 mb-5 border border-blue-50 relative overflow-hidden">
              <div className="relative z-10 flex flex-col sm:flex-row items-start sm:items-center gap-3">
                <div className="flex items-center gap-2 flex-1">
                  <Heart className="w-4 h-4 text-rose-500 fill-rose-500 animate-pulse flex-shrink-0" />
                  <p className="text-slate-700 text-xs font-semibold">{t('introduction.keepFree', 'Help us keep PathLab free')}</p>
                </div>
                <a href="https://ko-fi.com/pathlab" target="_blank" rel="noopener noreferrer" className="w-full sm:w-auto">
                  <Button variant="outline" className="w-full sm:w-auto text-xs px-4 h-8 rounded-lg bg-white border-[color:var(--landing-border)]">
                    {t('introduction.donate', 'Donate')} <ExternalLink className="w-3 h-3 ml-1.5 opacity-70" />
                  </Button>
                </a>
              </div>
            </div>

            <Button onClick={onPrimaryCta} variant="outline" className="w-full h-12 rounded-xl text-base border-[color:var(--landing-border)]">
              {t(PRICING_TIERS.individual.ctaKey, 'Get Started')} <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </div>

          {/* Enterprise */}
          <div className="relative bg-gradient-to-b from-[#F4F9FC] to-white border border-blue-200 rounded-[28px] p-8 h-full flex flex-col hover:shadow-xl transition-all duration-300 overflow-hidden">
            <div className="absolute top-0 right-0 w-64 h-64 bg-blue-400/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/3"></div>
            
            <div className="relative z-10 flex flex-col h-full">
              <p className="text-[color:var(--landing-primary)] font-bold text-sm uppercase tracking-wider mb-2">
                {t(PRICING_TIERS.enterprise.titleKey, 'Enterprise')}
              </p>
              <div className="flex items-baseline gap-1 mb-3">
                <span className="text-4xl font-extrabold tracking-tight text-[color:var(--landing-text-primary)]">
                  {t(PRICING_TIERS.enterprise.priceKey, 'Custom')}
                </span>
              </div>
              <p className="text-[color:var(--landing-text-secondary)] text-sm leading-relaxed mb-6">
                {t(PRICING_TIERS.enterprise.descKey, 'For hospitals and large labs.')}
              </p>
              <ul className="space-y-3 mb-8 flex-1">
                {PRICING_TIERS.enterprise.featuresKeys.map((featKey) => (
                  <li key={featKey} className="flex items-start gap-3 text-sm text-[color:var(--landing-text-primary)]">
                    <Check className="w-4 h-4 text-[color:var(--landing-primary)] mt-0.5 flex-shrink-0" />
                    <span>{t(featKey, featKey)}</span>
                  </li>
                ))}
              </ul>
              
              <a href="mailto:jhc@ust.hk" className="block">
                <Button variant="primary" className="w-full h-12 rounded-xl text-base bg-[color:var(--landing-primary)] text-white hover:bg-[color:var(--landing-primary-deep)] shadow-md shadow-blue-500/20">
                  {t(PRICING_TIERS.enterprise.ctaKey, 'Contact Sales')} <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
