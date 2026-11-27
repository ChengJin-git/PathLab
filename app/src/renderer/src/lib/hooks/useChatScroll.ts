import { useCallback, useLayoutEffect, useRef, useState } from 'react'

/** Follow growing Chat/research content until the reader intentionally scrolls up. */
export function useChatScroll(conversationId: string | null, visible: boolean) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null)
  const [content, setContent] = useState<HTMLDivElement | null>(null)
  const following = useRef(true)
  const previousTop = useRef(0)
  const [away, setAway] = useState(false)
  const jumpToLatest = useCallback(() => {
    following.current = true
    setAway(false)
    if (container) {
      container.scrollTop = container.scrollHeight
      previousTop.current = container.scrollTop
    }
  }, [container])

  useLayoutEffect(() => {
    if (!container || !content || !visible) return
    // A newly opened conversation always starts at its latest content.
    jumpToLatest()
    const nearBottom = () => container.scrollHeight - container.clientHeight - container.scrollTop < 64
    const onScroll = () => {
      const near = nearBottom()
      if (container.scrollTop < previousTop.current - 1) following.current = near
      if (near) following.current = true
      previousTop.current = container.scrollTop
      setAway(!near)
    }
    const onResize = () => {
      if (following.current) jumpToLatest()
      else setAway(!nearBottom())
    }
    container.addEventListener('scroll', onScroll, { passive: true })
    const observer = new ResizeObserver(onResize)
    observer.observe(container)
    observer.observe(content)
    return () => {
      container.removeEventListener('scroll', onScroll)
      observer.disconnect()
    }
  }, [container, content, conversationId, visible, jumpToLatest])

  return { containerRef: setContainer, contentRef: setContent, away, jumpToLatest }
}
