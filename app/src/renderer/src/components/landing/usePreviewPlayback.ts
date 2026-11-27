import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { animate, useInView, useMotionValue } from 'framer-motion'

const motionQuery = '(prefers-reduced-motion: reduce)'
const subscribeToMotion = (notify: () => void) => {
  const query = window.matchMedia(motionQuery)
  query.addEventListener('change', notify)
  return () => query.removeEventListener('change', notify)
}
export function usePreviewReducedMotion() {
  return useSyncExternalStore(subscribeToMotion, () => window.matchMedia(motionQuery).matches, () => false)
}

/** Autoplay only while visible. Pausing preserves progress; choosing a step stops playback. */
export function usePreviewPlayback(count: number, duration = 5200) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: .3 })
  const reducedMotion = usePreviewReducedMotion()
  const [stage, setStage] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [pageVisible, setPageVisible] = useState(() => !document.hidden)
  const progress = useMotionValue(0)
  const running = playing && inView && pageVisible && !reducedMotion

  useEffect(() => {
    const changed = () => setPageVisible(!document.hidden)
    document.addEventListener('visibilitychange', changed)
    return () => document.removeEventListener('visibilitychange', changed)
  }, [])

  useEffect(() => {
    if (!running) return
    const controls = animate(progress, 1, {
      duration: Math.max(.05, (1 - progress.get()) * duration / 1000),
      ease: 'linear',
      onComplete: () => {
        progress.set(0)
        setStage(value => (value + 1) % count)
      },
    })
    return () => controls.stop()
  }, [running, stage, progress, count, duration])

  const select = (value: number) => {
    setPlaying(false)
    progress.set(0)
    setStage(value)
  }

  return { ref, stage, playing, running, reducedMotion, progress, select, toggle: () => setPlaying(value => !value) }
}
