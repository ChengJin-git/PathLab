import { useTranslation } from 'react-i18next'

export function TrustStrip() {
  const { t } = useTranslation()
  return <div className="public-trust-strip public-container">{[1, 2, 3].map(item => <span key={item}>{t(`publicExperience.strip${item}`)}</span>)}</div>
}
