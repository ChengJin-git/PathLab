import { useState, useEffect } from 'react'
import { HeroDemoPhase } from '../../types/landing'
import { useReducedMotionSafe } from './useReducedMotionSafe'

interface UseHeroDemoStateProps {
  promptText: string
  configItemCount: number
  isInView: boolean
  progressTarget: number
}

export function useHeroDemoState({
  promptText,
  configItemCount,
  isInView,
  progressTarget
}: UseHeroDemoStateProps) {
  const [phase, setPhase] = useState<HeroDemoPhase>('idle')
  const [typedText, setTypedText] = useState('')
  const [configVisibleCount, setConfigVisibleCount] = useState(0)
  const [progress, setProgress] = useState(0)

  const prefersReducedMotion = useReducedMotionSafe()

  useEffect(() => {
    if (!isInView) return

    if (prefersReducedMotion) {
      setPhase('running')
      setTypedText(promptText)
      setConfigVisibleCount(configItemCount)
      setProgress(progressTarget)
      return
    }

    if (phase === 'idle') {
      const t = setTimeout(() => setPhase('typing'), 200)
      return () => clearTimeout(t)
    }
  }, [isInView, prefersReducedMotion, phase, promptText, configItemCount, progressTarget])

  useEffect(() => {
    if (phase !== 'typing') return
    
    let currentIndex = 0
    let typingInterval: NodeJS.Timeout
    
    const typingSpeed = 1200 / Math.max(promptText.length, 1) // ~1.2s total
    
    typingInterval = setInterval(() => {
      currentIndex++
      setTypedText(promptText.slice(0, currentIndex))
      if (currentIndex === promptText.length) {
        clearInterval(typingInterval)
        setTimeout(() => setPhase('intent-visible'), 100)
      }
    }, typingSpeed)

    return () => clearInterval(typingInterval)
  }, [phase, promptText])

  useEffect(() => {
    if (phase === 'intent-visible') {
      const t = setTimeout(() => setPhase('config-visible'), 450)
      return () => clearTimeout(t)
    }
  }, [phase])

  useEffect(() => {
    if (phase === 'config-visible') {
      if (configVisibleCount < configItemCount) {
        const t = setTimeout(() => setConfigVisibleCount(prev => prev + 1), 90)
        return () => clearTimeout(t)
      } else {
        const t = setTimeout(() => setPhase('run-ready'), 250)
        return () => clearTimeout(t)
      }
    }
  }, [phase, configVisibleCount, configItemCount])

  useEffect(() => {
    if (phase === 'queueing') {
      const t = setTimeout(() => {
        setPhase('running')
        setProgress(18)
      }, 900)
      return () => clearTimeout(t)
    }
  }, [phase])

  useEffect(() => {
    if (phase === 'running' && progress < progressTarget && !prefersReducedMotion) {
      const delay = 1000 / (progressTarget - 18)
      const t = setTimeout(() => {
        setProgress(prev => {
          const next = Math.min(prev + 1, progressTarget)
          if (next === progressTarget) {
            setTimeout(() => setPhase('completed'), 300)
          }
          return next
        })
      }, delay)
      return () => clearTimeout(t)
    } else if (phase === 'running' && progress >= progressTarget) {
      setPhase('completed')
    }
  }, [phase, progress, progressTarget, prefersReducedMotion])

  const startRun = () => {
    if (phase === 'run-ready') {
      setPhase('queueing')
    } else if (phase === 'completed') {
      setTypedText('')
      setConfigVisibleCount(0)
      setProgress(0)
      setPhase('typing')
    }
  }

  const phaseIndex = [
    'idle', 'typing', 'intent-visible', 'config-visible', 
    'run-ready', 'queueing', 'running', 'completed'
  ].indexOf(phase)

  return {
    phase,
    typedText,
    configVisibleCount,
    progress,
    startRun,
    isReady: phase === 'run-ready' || phase === 'completed',
    showIntent: phaseIndex >= 2,
    showConfig: phaseIndex >= 3,
    showRunCard: phaseIndex >= 4 && phaseIndex < 7,
    showResults: phase === 'completed'
  }
}
