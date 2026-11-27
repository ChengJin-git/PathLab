import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import { Reveal } from './Reveal'
import { LayerStack } from './LayerStack'

export function EvidenceLayer() {
  const { t } = useTranslation()
  return (
    <section className="public-section public-evidence">
      <div className="public-container public-evidence__layout">
        <Reveal className="public-section-heading"><p className="public-eyebrow">{t('publicExperience.evidenceEyebrow')}</p><h2>{t('publicExperience.evidenceTitle')}</h2><p>{t('publicExperience.evidenceDesc')}</p><ul>{[1, 2, 3].map(item => <li key={item}><Check size={17} />{t(`publicExperience.evidence${item}`)}</li>)}</ul></Reveal>
        <LayerStack />
      </div>
    </section>
  )
}
