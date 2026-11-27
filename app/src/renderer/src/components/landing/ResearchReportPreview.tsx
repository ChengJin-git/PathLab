import { useTranslation } from 'react-i18next'
import { FileText, Link2 } from 'lucide-react'

/** An outline of the real report structure, without invented findings or metrics. */
export function ResearchReportPreview({ compact = false, animated = false }: { compact?: boolean; animated?: boolean }) {
  const { t } = useTranslation()
  return (
    <article className={`research-report-preview ${compact ? 'research-report-preview--compact' : ''} ${animated ? 'research-report-preview--animated' : ''}`} aria-label={t('publicExperience.reportPreview')}>
      <header><FileText size={17} strokeWidth={1.5} /><span>{t('publicExperience.reportPreview')}</span></header>
      <h4>{t('publicExperience.reportTitle')}</h4>
      <ol>
        {[1, 2, 3].map(section => (
          <li key={section} className={animated ? 'demo-build-item' : undefined} style={animated ? { animationDelay: `${section * .35}s` } : undefined}>
            <span className="research-report-preview__number">0{section}</span>
            <div><strong>{t(`publicExperience.reportSection${section}`)}</strong><p>{t(`publicExperience.reportSection${section}Desc`)}</p></div>
          </li>
        ))}
      </ol>
      <footer className={animated ? 'demo-build-item' : undefined} style={animated ? { animationDelay: '1.4s' } : undefined}><Link2 size={14} />{t('publicExperience.reportSources')}</footer>
    </article>
  )
}
