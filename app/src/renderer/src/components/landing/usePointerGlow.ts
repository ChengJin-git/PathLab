import { useEffect, type RefObject } from 'react'

/** Surfaces that answer the pointer with a soft light (see public-experience.css). */
export const GLOW_SELECTOR = '.public-capability, .public-workflow__step, .public-pricing__tier, .login-legal__links button'

/**
 * One delegated listener per page: the hovered surface receives --glow-x/--glow-y
 * (local px) once per frame. Fine pointers only; touch and reduced motion skip it.
 */
export function usePointerGlow(rootRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = rootRef.current
    if (!root || typeof window.matchMedia !== 'function') return
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    let frame = 0
    let target: HTMLElement | null = null
    let x = 0
    let y = 0
    const write = () => {
      frame = 0
      if (!target) return
      target.style.setProperty('--glow-x', `${x.toFixed(0)}px`)
      target.style.setProperty('--glow-y', `${y.toFixed(0)}px`)
    }
    const clear = (element: HTMLElement | null) => {
      element?.style.removeProperty('--glow-x')
      element?.style.removeProperty('--glow-y')
    }
    const move = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return
      const next = (event.target as Element | null)?.closest?.(GLOW_SELECTOR) as HTMLElement | null
      if (next !== target) { clear(target); target = next }
      if (!target) return
      const bounds = target.getBoundingClientRect()
      x = event.clientX - bounds.left
      y = event.clientY - bounds.top
      if (!frame) frame = requestAnimationFrame(write)
    }
    const leave = () => { clear(target); target = null }
    root.addEventListener('pointermove', move, { passive: true })
    root.addEventListener('pointerleave', leave)
    return () => {
      root.removeEventListener('pointermove', move)
      root.removeEventListener('pointerleave', leave)
      if (frame) cancelAnimationFrame(frame)
      clear(target)
    }
  }, [rootRef])
}
