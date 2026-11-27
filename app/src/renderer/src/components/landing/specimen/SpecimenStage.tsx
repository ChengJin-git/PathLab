import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { getSpecimenEngine } from './engine'

/** Hosts the shared 3D specimen canvas. Framing is set in CSS on `.specimen-stage`. */
export function SpecimenStage({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  const hostRef = useRef<HTMLDivElement>(null)
  const reduceMotion = Boolean(useReducedMotion())
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const host = hostRef.current
    const engine = host ? getSpecimenEngine() : null
    if (!host || !engine) return
    engine.attach(host)
    setReady(true)
    let observer: IntersectionObserver | undefined
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver(([entry]) => engine.setInView(entry.isIntersecting), { threshold: 0.02 })
      observer.observe(host)
    }
    return () => { observer?.disconnect(); engine.detach(host) }
  }, [])

  useEffect(() => { getSpecimenEngine()?.setStatic(reduceMotion) }, [reduceMotion, ready])

  return (
    <div className={`specimen-stage ${ready ? 'is-ready' : ''} ${className}`}>
      <div ref={hostRef} className="specimen-stage__host" role="img" aria-label={t('publicExperience.stageLabel')} />
    </div>
  )
}
