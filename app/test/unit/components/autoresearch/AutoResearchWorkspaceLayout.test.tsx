import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import AutoResearchWorkspaceLayout from '@renderer/components/autoresearch/AutoResearchWorkspaceLayout'

describe('AutoResearchWorkspaceLayout', () => {
  it('uses a wider content frame with tighter desktop page margins', () => {
    render(
      <MemoryRouter initialEntries={['/autoresearch/sessions/s1']}>
        <Routes>
          <Route element={<AutoResearchWorkspaceLayout />}>
            <Route path="/autoresearch/sessions/:id" element={<main>Session content</main>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    const content = screen.getByTestId('autoresearch-workspace-content')
    expect(content).toHaveClass('max-w-7xl')
    expect(content).toHaveClass('p-3')
    expect(content).toHaveClass('sm:p-4')
    expect(content).toHaveClass('lg:p-5')
    expect(content).not.toHaveClass('max-w-5xl')
    expect(content).not.toHaveClass('lg:p-8')
    expect(screen.getByText('Session content')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
