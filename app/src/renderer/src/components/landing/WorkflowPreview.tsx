import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { Database, FileText, FolderOpen, Layers2, Microscope } from 'lucide-react'
import { ResearchPreview, OutputsPreview } from './ResearchPreview'
export type PreviewMode = 'viewer' | 'research' | 'results'

const chapters: PreviewMode[] = ['viewer', 'research', 'results']

/** Each chapter shows a different part of the product, rather than another viewer shell. */
export function WorkflowPreview({ mode, onModeChange, running = false, reducedMotion = false }: {
  mode: PreviewMode
  onModeChange: (mode: PreviewMode) => void
  running?: boolean
  reducedMotion?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className={`workflow-preview workflow-preview--${mode}`} data-motion={reducedMotion ? 'reduced' : running ? 'playing' : 'paused'}>
      {chapters.map(chapter => (
        <motion.div
          key={chapter}
          className={`workflow-preview__chapter ${mode === chapter ? 'is-active' : ''}`}
          aria-hidden={mode !== chapter}
          initial={false}
          animate={{ opacity: mode === chapter ? 1 : 0, y: mode === chapter || reducedMotion ? 0 : 8 }}
          transition={{ duration: reducedMotion ? 0 : .3 }}
        >
          {chapter === 'viewer' && (
            <div className="workflow-library">
              <div className="workflow-library__heading">
                <FolderOpen size={20} strokeWidth={1.5} />
                <div><h3>{t('publicExperience.collection')}</h3><p>{t('publicExperience.collectionNote')}</p></div>
              </div>
              <div className="workflow-library__slide demo-build-item" style={{ animationDelay: '.1s' }}>
                <span className="workflow-library__thumb" aria-hidden="true"><Microscope size={22} strokeWidth={1.5} /></span>
                <div><strong>{t('publicExperience.slideName')}</strong></div>
                <span className="workflow-library__type">WSI</span>
              </div>
              <div className="workflow-library__row demo-build-item" style={{ animationDelay: '.5s' }}><FileText size={18} /><span>{t('publicExperience.taskLabels')}</span><span>CSV</span></div>
              <div className="workflow-library__row demo-build-item" style={{ animationDelay: '.9s' }}><Layers2 size={18} /><span>{t('publicExperience.dataLabel3')}</span><Database size={16} /></div>
            </div>
          )}
          {chapter === 'research' && <ResearchPreview onResults={() => onModeChange('results')} animated />}
          {chapter === 'results' && <OutputsPreview onSlide={() => onModeChange('viewer')} animated />}
        </motion.div>
      ))}
    </div>
  )
}
