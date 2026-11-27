import { useTranslation } from 'react-i18next'
import { Database, FolderOpen, Layers2 } from 'lucide-react'
import { Reveal } from './Reveal'
import { AgentResearchDemo } from './AgentResearchDemo'
import { KnowledgePreview } from './KnowledgePreview'

export function CapabilityShowcase() {
  const { t } = useTranslation()
  return (
    <section id="capabilities" className="public-section public-capabilities">
      <div className="public-container">
        <Reveal className="public-section-heading"><p className="public-eyebrow">{t('publicExperience.capabilitiesEyebrow')}</p><h2>{t('publicExperience.capabilitiesTitle')}</h2></Reveal>
        <div className="public-capabilities__grid">
          <Reveal className="public-capability public-capability--agent">
            <div className="public-capability__copy">
              <h3>{t('publicExperience.tasksTitle')}</h3>
              <p>{t('publicExperience.tasksDesc')}</p>
            </div>
            <AgentResearchDemo />
          </Reveal>
          <Reveal className="public-capability public-capability--data">
            <div className="public-capability__copy"><h3>{t('publicExperience.dataTitle')}</h3><p>{t('publicExperience.dataDesc')}</p></div>
            <div className="public-data-preview">
              <div className="public-data-preview__slides" aria-hidden="true">{[0, 1, 2].map(index => <span key={index} />)}</div>
              <div className="public-data-preview__rows">{[Database, FolderOpen, Layers2].map((Icon, index) => <div key={index}><Icon size={17} strokeWidth={1.5} /><span>{t(`publicExperience.dataLabel${index + 1}`)}</span></div>)}</div>
            </div>
          </Reveal>
          <Reveal className="public-capability public-capability--knowledge" delay={0.08}>
            <div className="public-capability__copy"><h3>{t('publicExperience.knowledgeTitle')}</h3><p>{t('publicExperience.knowledgeDesc')}</p></div>
            <KnowledgePreview />
          </Reveal>
        </div>
      </div>
    </section>
  )
}
