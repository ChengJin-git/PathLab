import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ResultsViewerPage from '../../../src/renderer/src/pages/ResultsViewerPage'
import { TooltipProvider } from '../../../src/renderer/src/components/ui/tooltip'
import enUS from '../../../src/renderer/src/locales/en-US.json'
import zhCN from '../../../src/renderer/src/locales/zh-CN.json'
import zhHK from '../../../src/renderer/src/locales/zh-HK.json'

const LOCALES = [
  { name: 'en-US', data: enUS },
  { name: 'zh-CN', data: zhCN },
  { name: 'zh-HK', data: zhHK },
]

const authState = {
  isAdmin: false,
}

vi.mock('react-i18next', async importOriginal => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) => key,
    }),
  }
})

vi.mock('../../../src/renderer/src/contexts/AuthContext', () => ({
  useAuth: () => authState,
}))

const mockInvalidateQueries = vi.fn()

vi.mock('@tanstack/react-query', async importOriginal => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>()
  return {
    ...actual,
    useQueryClient: () => ({
      invalidateQueries: mockInvalidateQueries,
    }),
  }
})

const backgroundTaskMocks = {
  rawTrainingTasks: null as unknown,
  trainingSseSubscribed: false,
}

vi.mock('../../../src/renderer/src/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({
    analysisTasks: [],
    subscribeAnalysisSSE: () => () => {},
    rawTrainingTasks: backgroundTaskMocks.rawTrainingTasks,
    subscribeTrainingSSE: () => {
      backgroundTaskMocks.trainingSseSubscribed = true
      return () => {}
    },
  }),
}))

describe('ResultsViewerPage training SSE invalidation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockInvalidateQueries.mockClear()
    authState.isAdmin = false
    backgroundTaskMocks.rawTrainingTasks = null
    backgroundTaskMocks.trainingSseSubscribed = false
  })

  it('subscribes to training SSE on mount', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })

    vi.spyOn(console, 'error').mockImplementation(() => {})

    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter>
            <ResultsViewerPage />
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(backgroundTaskMocks.trainingSseSubscribed).toBe(true)
    })

    unmount()
  })

  it('has resultsPage search keys in all locale files', () => {
    const keys = [
      'searchModels',
      'noMatchingModels',
      'searchTasks',
      'noMatchingTasks',
    ]
    for (const { name, data } of LOCALES) {
      for (const key of keys) {
        expect(
          (data as any).resultsPage?.[key],
          `Missing resultsPage.${key} in ${name}`
        ).toBeDefined()
      }
    }
  })

  it('invalidates results-tasks query when rawTrainingTasks changes from SSE', async () => {
    backgroundTaskMocks.rawTrainingTasks = null
    backgroundTaskMocks.trainingSseSubscribed = false

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })

    vi.spyOn(console, 'error').mockImplementation(() => {})

    const { unmount, rerender } = render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter>
            <ResultsViewerPage />
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(backgroundTaskMocks.trainingSseSubscribed).toBe(true)
    })

    expect(mockInvalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ['results-tasks'] }),
    )

    backgroundTaskMocks.rawTrainingTasks = [{ task_id: 'task-1', status: 'completed' }]

    rerender(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter>
            <ResultsViewerPage />
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(mockInvalidateQueries).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ['results-tasks'] }),
      )
    })

    unmount()
  })
})
