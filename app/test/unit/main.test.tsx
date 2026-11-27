import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'

const mocks = vi.hoisted(() => ({
  render: vi.fn(),
  initializeApiConfig: vi.fn(),
  updateApiBase: vi.fn(),
  bootstrapTrainingOptions: vi.fn(),
}))

vi.mock('react-dom/client', () => ({
  createRoot: vi.fn(() => ({ render: mocks.render })),
}))

vi.mock('@tanstack/react-query', () => ({
  QueryClientProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@tanstack/react-query-devtools', () => ({
  ReactQueryDevtools: () => null,
}))

vi.mock('react-router-dom', () => ({
  BrowserRouter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  HashRouter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@renderer/App', () => ({
  default: () => <div data-testid="app" />,
}))

vi.mock('@renderer/contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({
  BackgroundTaskProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@renderer/contexts/ToastContext', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@renderer/components/ui/tooltip', () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@renderer/config', () => ({
  initializeApiConfig: mocks.initializeApiConfig,
  updateApiBase: mocks.updateApiBase,
}))

vi.mock('@renderer/lib/utils/queryClient', () => ({
  queryClient: {},
}))

vi.mock('@renderer/constants/trainingOptionsBootstrap', () => ({
  bootstrapTrainingOptions: mocks.bootstrapTrainingOptions,
}))

vi.mock('@renderer/lib/autoresearchStandalone', () => ({
  isAutoResearchStandaloneMode: () => false,
}))

vi.mock('@renderer/i18n', () => ({ i18nReady: Promise.resolve() }))

describe('main bootstrap', () => {
  beforeEach(() => {
    vi.resetModules()
    document.body.innerHTML = '<div id="root"></div>'
    mocks.render.mockClear()
    mocks.initializeApiConfig.mockReset().mockResolvedValue(undefined)
    mocks.updateApiBase.mockClear()
    mocks.bootstrapTrainingOptions.mockReset().mockReturnValue(new Promise(() => {}))
  })

  it('renders the app before training options hydration finishes', async () => {
    await import('@renderer/main')

    await waitFor(() => expect(mocks.render).toHaveBeenCalled())
    expect(mocks.bootstrapTrainingOptions).toHaveBeenCalled()
  })
})
