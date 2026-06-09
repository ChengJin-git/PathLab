import React, { useRef, useEffect } from 'react'

interface TencentCaptchaProps {
  appId: string
  onVerify: (ticket: string, randstr: string) => void
  onExpire?: () => void
  onError?: () => void
}

declare global {
  interface Window {
    TencentCaptcha?: new (
      element: HTMLElement | string,
      appId: string,
      callback: (res: { ret: number; ticket?: string; randstr?: string }) => void,
      options?: Record<string, unknown>
    ) => { show: () => void }
  }
}

export function TencentCaptcha({ appId, onVerify, onExpire, onError }: TencentCaptchaProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const scriptLoaded = useRef(false)

  useEffect(() => {
    if (!containerRef.current || scriptLoaded.current) return

    const loadScript = () => {
      return new Promise<void>((resolve, reject) => {
        if (window.TencentCaptcha) {
          resolve()
          return
        }

        const script = document.createElement('script')
        script.src = 'https://ca.turing.captcha.qcloud.com/TJNCaptcha-global.js'
        script.async = true
        script.onload = () => resolve()
        script.onerror = () => reject(new Error('Failed to load Tencent Captcha script'))
        document.head.appendChild(script)
      })
    }

    const initCaptcha = async () => {
      try {
        await loadScript()
        scriptLoaded.current = true

        if (!containerRef.current || !window.TencentCaptcha) return

        const captcha = new window.TencentCaptcha(
          containerRef.current,
          appId,
          (res) => {
            if (res.ret === 0 && res.ticket && res.randstr) {
              onVerify(res.ticket, res.randstr)
            } else if (res.ret === 2) {
              onExpire?.()
            } else {
              onError?.()
            }
          },
          {}
        )
        captcha.show()
      } catch (err) {
        console.error('Tencent Captcha init error:', err)
        onError?.()
      }
    }

    initCaptcha()

    return () => {
      const scripts = document.querySelectorAll('script[src*="TJNCaptcha-global.js"]')
      scripts.forEach((s) => s.remove())
      scriptLoaded.current = false
    }
  }, [appId, onVerify, onExpire, onError])

  return <div ref={containerRef} className="w-full" />
}
