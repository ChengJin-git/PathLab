import { useState, useEffect, useRef } from 'react'

export function useStickyStoryState(numSteps: number) {
  const [activeStep, setActiveStep] = useState(0)
  const stepRefs = useRef<(HTMLDivElement | null)[]>([])

  const registerStepRef = (index: number) => (el: HTMLDivElement | null) => {
    stepRefs.current[index] = el
  }

  useEffect(() => {
    const observers: IntersectionObserver[] = []
    
    stepRefs.current.forEach((ref, index) => {
      if (!ref) return
      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            if (entry.intersectionRatio >= 0.4) {
               setActiveStep(index)
            }
          }
        },
        {
          rootMargin: '-20% 0px -40% 0px',
          threshold: [0.3, 0.4, 0.5, 0.6]
        }
      )
      observer.observe(ref)
      observers.push(observer)
    })

    return () => {
      observers.forEach(obs => obs.disconnect())
    }
  }, [numSteps])

  return { activeStep, registerStepRef }
}
