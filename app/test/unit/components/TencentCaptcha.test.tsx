import React from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TencentCaptcha } from '@renderer/components/TencentCaptcha'

describe('TencentCaptcha', () => {
  const callbacks: Array<(res: { ret: number; ticket?: string; randstr?: string }) => void> = []
  const captchaConstructor = vi.fn()

  beforeEach(() => {
    callbacks.length = 0
    captchaConstructor.mockReset()

    ;(window as any).TencentCaptcha = class {
      show = vi.fn()

      constructor(element: HTMLElement | string, appId: string, callback: (res: { ret: number; ticket?: string; randstr?: string }) => void) {
        callbacks.push(callback)
        captchaConstructor(element, appId, callback)
      }
    }
  })

  afterEach(() => {
    delete (window as any).TencentCaptcha
    document.head.innerHTML = ''
  })

  it('does not reinitialize after verification causes parent state to update', async () => {
    function Harness() {
      const [ticket, setTicket] = React.useState('')

      return (
        <>
          <TencentCaptcha
            appId="tencent-app-id"
            onVerify={(verifiedTicket) => setTicket(verifiedTicket)}
            onExpire={() => setTicket('')}
            onError={() => setTicket('')}
          />
          <span data-testid="ticket">{ticket}</span>
        </>
      )
    }

    render(<Harness />)

    await waitFor(() => expect(captchaConstructor).toHaveBeenCalledTimes(1))

    act(() => {
      callbacks[0]({ ret: 0, ticket: 'ticket-123', randstr: 'rand-456' })
    })

    expect(screen.getByTestId('ticket')).toHaveTextContent('ticket-123')
    await waitFor(() => expect(captchaConstructor).toHaveBeenCalledTimes(1))
  })
})
