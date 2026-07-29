import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getPaperFileJson, type PaperRunDetail } from '@renderer/api/papers'
import { OutlineTab } from '@renderer/components/paper/OutlineTab'
import {
  awaitingOutlineApprovalRunFixture,
  makeOutlineUnavailableErrorFixture,
  outlineDocumentFixture,
  PAPER_ID_FIXTURE,
  runningOutliningRunFixture,
} from './outlineTestFixtures'

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) => key,
    }),
  }
})

vi.mock('@renderer/api/papers', () => ({
  getPaperFileJson: vi.fn(),
  putPaperOutline: vi.fn(),
}))

vi.mock('@renderer/components/paper/SectionsTab', () => ({
  labelForSection: (section: string) => section,
}))

function renderOutlineTab(run: PaperRunDetail = runningOutliningRunFixture) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  const view = render(
    <QueryClientProvider client={queryClient}>
      <OutlineTab paperId={PAPER_ID_FIXTURE} run={run} />
    </QueryClientProvider>,
  )

  return {
    ...view,
    rerenderWithRun(nextRun: PaperRunDetail) {
      view.rerender(
        <QueryClientProvider client={queryClient}>
          <OutlineTab paperId={PAPER_ID_FIXTURE} run={nextRun} />
        </QueryClientProvider>,
      )
    },
  }
}

describe('OutlineTab', () => {
  beforeEach(() => {
    vi.mocked(getPaperFileJson).mockReset()
  })

  it('shows the empty state while the outline artifact is unavailable', async () => {
    vi.mocked(getPaperFileJson).mockRejectedValueOnce(makeOutlineUnavailableErrorFixture())

    renderOutlineTab()

    expect(await screen.findByText('paperAgent.outline.emptyTitle')).toBeInTheDocument()
    await waitFor(() => {
      expect(getPaperFileJson).toHaveBeenCalledTimes(1)
    })
    expect(getPaperFileJson).toHaveBeenCalledWith(PAPER_ID_FIXTURE, 'drafts/outline.json')
  })

  it('does not refetch the missing outline while the run is still outlining', async () => {
    vi.mocked(getPaperFileJson).mockRejectedValueOnce(makeOutlineUnavailableErrorFixture())

    const { rerenderWithRun } = renderOutlineTab()

    expect(await screen.findByText('paperAgent.outline.emptyTitle')).toBeInTheDocument()

    rerenderWithRun({ ...runningOutliningRunFixture, title: 'Updated run fixture' })

    expect(getPaperFileJson).toHaveBeenCalledTimes(1)
  })

  it('does not refetch an outline that is already loaded at the approval gate', async () => {
    vi.mocked(getPaperFileJson)
      .mockRejectedValueOnce(makeOutlineUnavailableErrorFixture())
      .mockResolvedValueOnce(outlineDocumentFixture)

    const { rerenderWithRun } = renderOutlineTab()

    expect(await screen.findByText('paperAgent.outline.emptyTitle')).toBeInTheDocument()

    rerenderWithRun(awaitingOutlineApprovalRunFixture)
    expect(await screen.findByText('Explain the auto-refresh regression fixture.')).toBeInTheDocument()

    rerenderWithRun({ ...awaitingOutlineApprovalRunFixture, title: 'Updated approval fixture' })

    expect(getPaperFileJson).toHaveBeenCalledTimes(2)
  })

  it('loads an available outline once when mounted at the approval gate', async () => {
    vi.mocked(getPaperFileJson).mockResolvedValueOnce(outlineDocumentFixture)

    renderOutlineTab(awaitingOutlineApprovalRunFixture)

    expect(await screen.findByText('Explain the auto-refresh regression fixture.')).toBeInTheDocument()
    expect(getPaperFileJson).toHaveBeenCalledTimes(1)
  })

  it('loads the outline when the run reaches outline approval without a user click', async () => {
    vi.mocked(getPaperFileJson)
      .mockRejectedValueOnce(makeOutlineUnavailableErrorFixture())
      .mockResolvedValueOnce(outlineDocumentFixture)

    const { rerenderWithRun } = renderOutlineTab()

    expect(await screen.findByText('paperAgent.outline.emptyTitle')).toBeInTheDocument()

    rerenderWithRun(awaitingOutlineApprovalRunFixture)

    expect(await screen.findByText('Explain the auto-refresh regression fixture.')).toBeInTheDocument()
    expect(getPaperFileJson).toHaveBeenCalledTimes(2)
  })
})
