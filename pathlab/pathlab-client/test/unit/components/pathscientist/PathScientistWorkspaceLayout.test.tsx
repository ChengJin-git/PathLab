import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import PathScientistWorkspaceLayout from '@renderer/components/pathscientist/PathScientistWorkspaceLayout'

vi.mock('@renderer/components/pathscientist/PathScientistSessionSidebar', () => ({
  default: () => <aside>PathScientist sidebar</aside>,
}))

describe('PathScientistWorkspaceLayout', () => {
  it('uses a wider content frame with tighter desktop page margins', () => {
    render(
      <MemoryRouter initialEntries={['/pathscientist/sessions/s1']}>
        <Routes>
          <Route element={<PathScientistWorkspaceLayout />}>
            <Route path="/pathscientist/sessions/:id" element={<main>Session content</main>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    const content = screen.getByTestId('pathscientist-workspace-content')
    expect(content).toHaveClass('max-w-7xl')
    expect(content).toHaveClass('p-3')
    expect(content).toHaveClass('sm:p-4')
    expect(content).toHaveClass('lg:p-5')
    expect(content).not.toHaveClass('max-w-5xl')
    expect(content).not.toHaveClass('lg:p-8')
    expect(screen.getByText('Session content')).toBeInTheDocument()
  })
})
