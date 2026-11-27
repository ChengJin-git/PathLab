import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { Pause, Play } from 'lucide-react'
import { getSpecimenEngine } from './engine'

/** Labelled play/pause for the specimen stage, placed with the page copy. The ring tracks the cycle. */
export function StagePlayback({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()
  const ref = useRef<HTMLButtonElement>(null)
  const [engine] = useState(() => getSpecimenEngine())
  const [paused, setPaused] = useState(() => engine?.isPaused() ?? false)

  useEffect(() => engine?.onProgress(u => ref.current?.style.setProperty('--stage-progress', u.toFixed(4))), [engine])

  if (!engine || reduceMotion) return null
  const label = t(paused ? 'publicExperience.stagePlay' : 'publicExperience.stagePause')
  return (
    <button
      ref={ref}
      type="button"
      className={`public-button public-button--secondary stage-playback ${className}`}
      aria-pressed={paused}
      onClick={() => { const next = !paused; engine.setPaused(next); setPaused(next) }}
    >
      <span className="stage-playback__icon" aria-hidden="true">
        <svg className="stage-playback__ring" viewBox="0 0 40 40">
          <circle cx="20" cy="20" r="18" pathLength="100" />
          <circle className="stage-playback__progress" cx="20" cy="20" r="18" pathLength="100" />
        </svg>
        {paused ? <Play size={12} /> : <Pause size={12} />}
      </span>
      <span>{label}</span>
    </button>
  )
}
