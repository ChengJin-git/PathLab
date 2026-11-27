import { useId, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Check } from 'lucide-react'
import { SOLUTIONS_TABS } from '../../constants/landing/landing-solutions'
import { Reveal } from './Reveal'

export function SolutionsSection() {
  const { t } = useTranslation()
  const [activeIndex, setActiveIndex] = useState(0)
  const buttons = useRef<(HTMLButtonElement | null)[]>([])
  const id = useId()
  const reduceMotion = useReducedMotion()
  const active = SOLUTIONS_TABS[activeIndex]
  const navigate = (event: KeyboardEvent, index: number) => {
    let next = index
    if (event.key === 'ArrowRight') next = (index + 1) % SOLUTIONS_TABS.length
    else if (event.key === 'ArrowLeft') next = (index + SOLUTIONS_TABS.length - 1) % SOLUTIONS_TABS.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = SOLUTIONS_TABS.length - 1
    else return
    event.preventDefault()
    setActiveIndex(next)
    buttons.current[next]?.focus()
  }

  return (
    <section id="solutions" className="public-section public-solutions">
      <Reveal className="public-container">
        <div className="public-section-heading"><h2>{t('landing.solutions.title')}</h2></div>
        <div className="public-solutions__tabs" role="tablist" aria-label={t('landing.solutions.title')}>{SOLUTIONS_TABS.map((tab, index) => <button key={tab.key} type="button" role="tab" ref={element => { buttons.current[index] = element }} id={`${id}-${tab.key}`} aria-controls={`${id}-panel`} aria-selected={index === activeIndex} tabIndex={index === activeIndex ? 0 : -1} onClick={() => setActiveIndex(index)} onKeyDown={event => navigate(event, index)}>{index === activeIndex && <motion.span layoutId={`${id}-selection`} transition={{ duration: reduceMotion ? 0 : .25 }} />}<span>{t(tab.labelKey)}</span></button>)}</div>
        <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${active.key}`} tabIndex={0} className="public-solutions__panel"><AnimatePresence mode="wait" initial={false}><motion.div key={active.key} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduceMotion ? 0 : .15 }}><h3>{t(active.descKey)}</h3><ul>{active.bulletKeys.map(key => <li key={key}><Check size={17} />{t(key)}</li>)}</ul></motion.div></AnimatePresence></div>
      </Reveal>
    </section>
  )
}
