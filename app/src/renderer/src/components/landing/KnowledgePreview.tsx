import { useId, useState } from 'react'
import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { ChevronDown, FileText, Paperclip } from 'lucide-react'
import { usePreviewReducedMotion } from './usePreviewPlayback'
import botAvatar from '../../../public/images/bot_avatar.png'

export function KnowledgePreview() {
  const { t } = useTranslation()
  const [sourceOpen, setSourceOpen] = useState(false)
  const sourceId = useId()
  const reducedMotion = usePreviewReducedMotion()
  const entrance = (delay: number) => ({
    initial: reducedMotion ? false as const : { opacity: 0, y: 8 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, amount: .3 },
    transition: { duration: reducedMotion ? 0 : .4, delay: reducedMotion ? 0 : delay },
  })
  return (
    <div className="knowledge-preview">
      <motion.div className="knowledge-preview__attachment" {...entrance(0)}>
        <FileText size={20} strokeWidth={1.5} />
        <div><strong>{t('publicExperience.knowledgeDocument')}</strong><span>{t('publicExperience.knowledgeDocumentType')}</span></div>
        <Paperclip size={15} />
      </motion.div>
      <motion.p className="knowledge-preview__question" {...entrance(.25)}>{t('publicExperience.knowledgeQuestion')}</motion.p>
      <motion.div className="knowledge-preview__answer" {...entrance(.55)}>
        <img src={botAvatar} width="32" height="32" alt="PathLab" />
        <div>
          <p>{t('publicExperience.knowledgeAnswer')}</p>
          <button type="button" aria-expanded={sourceOpen} aria-controls={sourceId} onClick={() => setSourceOpen(value => !value)}>
            <span className="knowledge-preview__citation" aria-hidden="true">1</span>{t('publicExperience.knowledgeSource')}<ChevronDown size={14} />
          </button>
        </div>
      </motion.div>
      {sourceOpen && <motion.div id={sourceId} className="knowledge-preview__source" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : .2 }}>
        <span>{t('publicExperience.knowledgeSourceHeading')}</span>
        <blockquote>{t('publicExperience.knowledgeExcerpt')}</blockquote>
      </motion.div>}
    </div>
  )
}
