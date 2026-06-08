import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PathScientistNewSessionPage from '@renderer/pages/PathScientistNewSessionPage'
import { listPathScientistSkills } from '@renderer/api/pathscientist'

vi.mock('@renderer/api/pathscientist', () => ({
  listPathScientistSkills: vi.fn(),
  startPathScientistSession: vi.fn(),
}))

describe('PathScientistNewSessionPage', () => {
  beforeEach(() => {
    vi.mocked(listPathScientistSkills).mockResolvedValue({ items: [] })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('defaults max iterations to the PathScientist CLI default', () => {
    render(
      <MemoryRouter>
        <PathScientistNewSessionPage />
      </MemoryRouter>,
    )

    expect(screen.getByLabelText('Max iter')).toHaveValue(5)
  })
})
