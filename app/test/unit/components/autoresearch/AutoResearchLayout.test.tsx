import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import AutoResearchLayout from '@renderer/components/autoresearch/AutoResearchLayout'

describe('AutoResearchLayout', () => {
  it('keeps the top-right header empty', () => {
    render(
      <MemoryRouter>
        <AutoResearchLayout>
          <main>content</main>
        </AutoResearchLayout>
      </MemoryRouter>,
    )

    expect(screen.getByText('autoResearch.title')).toBeInTheDocument()
    expect(screen.queryByText('research agent')).not.toBeInTheDocument()
    expect(screen.queryByText('gpt-5.5')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^Sessions$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^New$/i })).not.toBeInTheDocument()
  })
})
