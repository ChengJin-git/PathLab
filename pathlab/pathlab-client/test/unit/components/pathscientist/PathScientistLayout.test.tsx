import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import PathScientistLayout from '@renderer/components/pathscientist/PathScientistLayout'

describe('PathScientistLayout', () => {
  it('keeps the top-right header empty', () => {
    render(
      <MemoryRouter>
        <PathScientistLayout>
          <main>content</main>
        </PathScientistLayout>
      </MemoryRouter>,
    )

    expect(screen.getByText('PathScientist')).toBeInTheDocument()
    expect(screen.queryByText('research agent')).not.toBeInTheDocument()
    expect(screen.queryByText('gpt-5.5')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^Sessions$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^New$/i })).not.toBeInTheDocument()
  })
})
