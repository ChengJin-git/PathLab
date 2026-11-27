import { useTranslation } from 'react-i18next'
import { Reveal } from './Reveal'

export function TrustDeploymentSection() {
  const { t } = useTranslation()
  return <section className="public-section public-deployment"><div className="public-container"><Reveal className="public-section-heading"><h2>{t('publicExperience.trustTitle')}</h2></Reveal><div className="public-deployment__grid">{[1, 2, 3].map(item => <Reveal key={item} delay={item * 0.04}><span className="public-deployment__number">0{item}</span><h3>{t(`publicExperience.trust${item}Title`)}</h3><p>{t(`publicExperience.trust${item}Desc`)}</p></Reveal>)}</div></div></section>
}
