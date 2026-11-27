import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, useReducedMotion, useSpring, useTransform, type MotionValue } from 'framer-motion'
import tissueImage from '../../../public/images/landing/tissue-detail.webp'
import heatmapImage from '../../../public/images/landing/evidence-heatmap.webp'
import { NEST_OUTLINES } from './evidenceAnnotations'

type Layer = 'slide' | 'annotations' | 'results'
const LAYERS: Layer[] = ['slide', 'annotations', 'results']

/** Slide, annotations and results drawn as one overlaid view; hover, focus or tap separates the layers. */
export function LayerStack() {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()
  const [hovered, setHovered] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [focus, setFocus] = useState<Layer | null>(null)
  const open = hovered || pinned
  const spread = useSpring(0, { stiffness: 140, damping: 22 })
  useEffect(() => { if (reduceMotion) spread.jump(open ? 1 : 0); else spread.set(open ? 1 : 0) }, [open, reduceMotion, spread])

  return (
    <div
      className="layer-stack"
      data-open={open || undefined}
      data-focus={focus ?? undefined}
      role="group"
      tabIndex={0}
      aria-label={t('publicExperience.layerStackLabel')}
      onPointerEnter={event => { if (event.pointerType === 'mouse') setHovered(true) }}
      onPointerLeave={() => { setHovered(false); setFocus(null) }}
      onClick={() => setPinned(value => !value)}
      onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setPinned(value => !value) } }}
    >
      <div className="layer-stack__scene">
        {LAYERS.map((layer, index) => (
          <LayerPlane key={layer} layer={layer} index={index} spread={spread} focused={focus === layer} onFocus={setFocus} label={t(`publicExperience.layer_${layer}`)} />
        ))}
      </div>
    </div>
  )
}

function LayerPlane({ layer, index, spread, focused, onFocus, label }: {
  layer: Layer
  index: number
  spread: MotionValue<number>
  focused: boolean
  onFocus: (layer: Layer | null) => void
  label: string
}) {
  const transform = useTransform(spread, value => `translateZ(${index * value * 95 + (focused ? 22 : 0) * value}px)`)
  return (
    <motion.div
      className={`layer-stack__plane layer-stack__plane--${layer} ${focused ? 'is-focused' : ''}`}
      style={{ transform }}
      onPointerEnter={() => onFocus(layer)}
    >
      {layer === 'slide' && <img src={tissueImage} alt="" width="2048" height="1532" loading="lazy" decoding="async" draggable={false} />}
      {layer === 'annotations' && (
        <svg viewBox="0 0 2048 1532" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          {NEST_OUTLINES.map(path => <path key={path} d={path} fill="#0a84ff14" stroke="#2997ff" strokeWidth="2.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />)}
        </svg>
      )}
      {layer === 'results' && <img src={heatmapImage} alt="" width="1024" height="766" loading="lazy" decoding="async" draggable={false} />}
      <span className="layer-stack__label">{label}</span>
    </motion.div>
  )
}
