import { useTranslation } from 'react-i18next'
import { ArrowRight } from 'lucide-react'
import { Reveal } from './Reveal'

export function FinalCTA({ onPrimaryCta }: { onPrimaryCta: () => void }) {
  const { t } = useTranslation()
  return <section className="public-section public-final"><Reveal className="public-container"><h2>{t('publicExperience.finalTitle')}</h2><p>{t('publicExperience.finalDesc')}</p><div className="public-actions"><button type="button" onClick={onPrimaryCta} className="public-button">{t('publicExperience.start')}<ArrowRight size={17} /></button><a href="mailto:jhc@ust.hk" className="public-link">{t('publicExperience.contact')}<ArrowRight size={17} /></a></div></Reveal></section>
}
