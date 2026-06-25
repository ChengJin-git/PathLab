import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '@renderer/App'

vi.mock('@renderer/pages/IntroductionPage', () => ({ default: () => <div>Intro page</div> }))
vi.mock('@renderer/pages/LoginPage', () => ({ default: () => <div>Login page</div> }))
vi.mock('@renderer/pages/AIChatPage', () => ({ default: () => <div>AI chat</div> }))
vi.mock('@renderer/pages/SettingsPage', () => ({ default: () => <div>Settings</div> }))
vi.mock('@renderer/pages/NewTaskPage', () => ({ default: () => <div>New task</div> }))
vi.mock('@renderer/pages/TaskListPage', () => ({ default: () => <div>Task list</div> }))
vi.mock('@renderer/pages/TaskDetailPage', () => ({ default: () => <div>Task detail</div> }))
vi.mock('@renderer/pages/ListPage', () => ({ default: () => <div>WSI list</div> }))
vi.mock('@renderer/pages/WSIViewerPage', () => ({ default: () => <div>WSI viewer</div> }))
vi.mock('@renderer/pages/UploadPage', () => ({ default: () => <div>Upload</div> }))
vi.mock('@renderer/pages/ResultsViewerPage', () => ({ default: () => <div>Results</div> }))
vi.mock('@renderer/pages/ReportGeneratorPage', () => ({ default: () => <div>Reports</div> }))
vi.mock('@renderer/pages/ToolsPage', () => ({ default: () => <div>Tools</div> }))
vi.mock('@renderer/pages/AutoResearchNewSessionPage', () => ({ default: () => <div>AutoResearch new</div> }))
vi.mock('@renderer/pages/AutoResearchSessionPage', () => ({ default: () => <div>AutoResearch detail</div> }))
vi.mock('@renderer/components/autoresearch/AutoResearchSessionSidebar', () => ({ default: () => <div>AutoResearch sidebar</div> }))
vi.mock('@renderer/components/Layout', () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }))
vi.mock('@renderer/components/ProtectedRoute', () => ({ ProtectedRoute: ({ children }: { children: React.ReactNode }) => <div data-testid="protected-route">{children}</div> }))

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function renderApp(path: string, standalone: boolean) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <LocationProbe />
      <App autoResearchStandalone={standalone} />
    </MemoryRouter>,
  )
}

describe('App AutoResearch standalone routing', () => {
  it('redirects the root page to AutoResearch when standalone mode is enabled', async () => {
    renderApp('/', true)

    expect(await screen.findByText('AutoResearch new')).toBeInTheDocument()
    expect(screen.queryByText('Intro page')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/autoresearch/new'))
  })

  it('redirects the login page to AutoResearch when standalone mode is enabled', async () => {
    renderApp('/login', true)

    expect(await screen.findByText('AutoResearch new')).toBeInTheDocument()
    expect(screen.queryByText('Login page')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/autoresearch/new'))
  })

  it('keeps the normal login page when standalone mode is disabled', () => {
    renderApp('/login', false)

    expect(screen.getByText('Login page')).toBeInTheDocument()
    expect(screen.queryByText('AutoResearch new')).not.toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
  })

  it('redirects unknown routes to AutoResearch instead of protected 404 in standalone mode', async () => {
    renderApp('/some-pathlab-route', true)

    expect(await screen.findByText('AutoResearch new')).toBeInTheDocument()
    expect(screen.queryByTestId('protected-route')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/autoresearch/new'))
  })
})
