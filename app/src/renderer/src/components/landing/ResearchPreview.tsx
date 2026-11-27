import { useTranslation } from 'react-i18next'
import { ArrowRight, Check, SlidersHorizontal } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'
import { ResearchReportPreview } from './ResearchReportPreview'
import botAvatar from '../../../public/images/bot_avatar.png'

export function ResearchPreview({ onResults, animated = false }: { onResults: () => void; animated?: boolean }) {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()
  return (
    <div className="research-preview">
      <div className="research-preview__conversation">
        <span className="public-eyebrow">{t('publicExperience.assistant')}</span>
        <p className="research-preview__prompt">{t('publicExperience.prompt')}</p>
        <div className="research-preview__response">
          <img className="research-preview__avatar" src={botAvatar} width="36" height="36" alt="PathLab" />
          <p>{t('publicExperience.response')}</p>
        </div>
      </div>
      <div className="research-preview__plan">
        <div className="research-preview__plan-heading">
          <span>{t('publicExperience.plan')}</span><SlidersHorizontal size={16} />
        </div>
        <ol>
          {[1, 2, 3].map(step => (
            <motion.li
              key={step}
              className={animated ? 'demo-build-item' : undefined}
              style={animated ? { animationDelay: `${step * .3}s` } : undefined}
              initial={reduceMotion || animated ? false : { opacity: 0, x: 5 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: .2, delay: reduceMotion || animated ? 0 : step * .12 }}
            ><span>0{step}</span>{t(`publicExperience.plan${step}`)}<Check size={15} /></motion.li>
          ))}
        </ol>
        <button type="button" className="public-link" onClick={onResults}>
          {t('publicExperience.reviewPlan')}<ArrowRight size={16} />
        </button>
      </div>
    </div>
  )
}

export function OutputsPreview({ onSlide, animated = false }: { onSlide: () => void; animated?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="outputs-preview">
      <div className="outputs-preview__intro">
        <span className="public-eyebrow">{t('publicExperience.results')}</span>
        <h3>{t('publicExperience.outputTitle')}</h3>
        <p>{t('publicExperience.outputDescription')}</p>
        <button type="button" className="public-link" onClick={onSlide}>
          {t('publicExperience.reviewSlide')}<ArrowRight size={16} />
        </button>
      </div>
      <ResearchReportPreview compact animated={animated} />
    </div>
  )
}
