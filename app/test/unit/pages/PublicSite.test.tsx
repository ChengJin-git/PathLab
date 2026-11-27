import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@renderer/pages/IntroductionPage', () => ({ default: () => <div>Landing page</div> }))
vi.mock('@renderer/pages/LoginPage', () => ({ default: () => <div>Login page</div> }))

import PublicSite from '@renderer/pages/PublicSite'

describe('PublicSite', () => {
  it('switches between landing and sign-in without another lazy boundary', () => {
    const { rerender } = render(<PublicSite page="landing" />)
    expect(screen.getByText('Landing page')).toBeInTheDocument()
    rerender(<PublicSite page="login" />)
    expect(screen.getByText('Login page')).toBeInTheDocument()
  })
})
