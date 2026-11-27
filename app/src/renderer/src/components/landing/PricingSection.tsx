import { useTranslation } from 'react-i18next'
import { Check, ArrowUpRight } from 'lucide-react'
import { PRICING_TIERS } from '../../constants/landing/landing-pricing'
import { Reveal } from './Reveal'

export function PricingSection({ onPrimaryCta }: { onPrimaryCta: () => void }) {
  const { t } = useTranslation()
  return (
    <section id="pricing" className="public-section public-pricing">
      <div className="public-container"><Reveal className="public-section-heading"><p className="public-eyebrow">{t('landing.nav.pricing')}</p><h2>{t('landing.pricing.title')}</h2></Reveal>
        <div className="public-pricing__grid">{Object.entries(PRICING_TIERS).map(([key, tier]) => <Reveal className="public-pricing__tier" key={key}><p className="public-eyebrow">{t(tier.titleKey)}</p><h3>{t(tier.priceKey)}</h3><p>{t(tier.descKey)}</p><ul>{tier.featuresKeys.map(feature => <li key={feature}><Check size={17} /><span>{t(feature)}</span></li>)}</ul>{key === 'individual' ? <button type="button" className="public-button" onClick={onPrimaryCta}>{t(tier.ctaKey)}<ArrowUpRight size={16} /></button> : <a href="mailto:jhc@ust.hk" className="public-button public-button--secondary">{t(tier.ctaKey)}<ArrowUpRight size={16} /></a>}</Reveal>)}</div>
        <p className="public-pricing__support">{t('introduction.keepFree')} <a href="https://ko-fi.com/pathlab" target="_blank" rel="noopener noreferrer">{t('introduction.donate')}<ArrowUpRight size={14} /></a></p>
      </div>
    </section>
  )
}
