import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, ChevronDown } from 'lucide-react'
import { motion, useReducedMotion, useScroll, useTransform } from 'framer-motion'
import { SpecimenStage } from './specimen/SpecimenStage'
import { StagePlayback } from './specimen/StagePlayback'

export function HeroSection({ onPrimaryCta }: { onPrimaryCta: () => void }) {
  const { t } = useTranslation()
  const heroRef = useRef<HTMLElement>(null)
  const reduceMotion = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ['start start', 'end start'] })
  const introY = useTransform(scrollYProgress, [0, 1], [0, reduceMotion ? 0 : -80])
  const introOpacity = useTransform(scrollYProgress, [0, 0.7], [1, reduceMotion ? 1 : 0])
  return (
    <section ref={heroRef} className="public-hero" id="product">
      <SpecimenStage className="public-hero__stage" />
      <div className="public-container public-hero__content">
        <motion.div className="public-hero__intro" style={{ y: introY, opacity: introOpacity }}>
          <h1>{t('publicExperience.heroTitle')}<br /><span>{t('publicExperience.heroAccent')}</span></h1>
          <p className="public-hero__description">{t('publicExperience.heroDescription')}</p>
          <div className="public-actions">
            <button type="button" className="public-button" onClick={onPrimaryCta}>{t('publicExperience.start')}<ArrowRight size={17} /></button>
            <a href="#workflow" className="public-button public-button--secondary">{t('publicExperience.explore')}<ChevronDown size={17} /></a>
            <StagePlayback />
          </div>
        </motion.div>
      </div>
    </section>
  )
}
