import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '../../src/renderer/src/components/ui/tooltip'
import AutoResearchSessionListItem from '../../src/renderer/src/components/autoresearch/AutoResearchSessionListItem'
import AutoResearchDeveloperSessionView from '../../src/renderer/src/components/autoresearch/views/AutoResearchDeveloperSessionView'
import type { AutoResearchSessionDetail, AutoResearchSessionSummary } from '../../src/renderer/src/types/autoresearch'

vi.mock('../../src/renderer/src/lib/useAutoResearchTranslation', () => ({
  useAutoResearchTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      if (key === 'autoResearch.sessionOwner') return `User: ${values?.name ?? ''}`
      if (key === 'autoResearch.sessionPage.sessionDetail') return 'Session Detail'
      if (key === 'autoResearch.sessionPage.description') return 'Structured AutoResearch execution console for this run.'
      if (key === 'autoResearch.sessionPage.researchQuestion') return 'Research Question'
      if (key === 'autoResearch.labels.stage') return 'Stage'
      if (key === 'autoResearch.labels.model') return 'Model'
      if (key === 'autoResearch.labels.events') return 'Events'
      if (key === 'autoResearch.labels.workspace') return 'Workspace'
      if (key === 'autoResearch.sessionPage.loading') return 'Loading'
      if (key === 'autoResearch.sessionActions.share') return 'Share'
      if (key === 'autoResearch.sessionActions.download') return 'Download'
      if (key === 'autoResearch.sessionActions.delete') return 'Delete'
      return key
    },
  }),
}))

vi.mock('../../src/renderer/src/components/autoresearch/AutoResearchExecutionConsole', () => ({
  default: () => <div data-testid="execution-console" />,
}))

vi.mock('../../src/renderer/src/components/settings/ConfirmDialog', () => ({
  ConfirmDialog: () => null,
}))

vi.mock('../../src/renderer/src/contexts/ToastContext', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

const noop = () => {}

function renderListItem(session: AutoResearchSessionSummary) {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <AutoResearchSessionListItem
          session={session}
          isDeleting={false}
          isDownloading={false}
          isSharing={false}
          onDeleteStart={noop}
          onDeleteEnd={noop}
          onDownloadStart={noop}
          onDownloadEnd={noop}
          onShareStart={noop}
          onShareEnd={noop}
          onSessionDeleted={noop}
        />
      </TooltipProvider>
    </MemoryRouter>,
  )
}

describe('AutoResearch owner chips', () => {
  it('shows the owner username in the session list card', () => {
    renderListItem({
      session_id: 'session-1',
      title: 'Gastric IM detection',
      question: 'Detect IM',
      status: 'failed',
      username: 'ywangrm',
    })

    const ownerChip = screen.getByTestId('autoresearch-session-owner-chip')
    expect(ownerChip).toHaveTextContent('ywangrm')
    expect(ownerChip.parentElement).toHaveClass('flex-nowrap')
    expect(ownerChip).toHaveClass('shrink-0')
    expect(ownerChip.parentElement).not.toHaveClass('flex-wrap')
  })

  it('shows the owner username in the session detail header', () => {
    const session: AutoResearchSessionDetail = {
      session_id: 'session-1',
      question: 'Detect IM',
      status: 'completed',
      stage: 'completed',
      model: 'gpt-5.5',
      username: 'Yihui Wang',
      events: [],
    }

    render(
      <AutoResearchDeveloperSessionView
        sessionId="session-1"
        session={session}
        events={[]}
        streamStatus="closed"
        displayTitle="Gastric intestinal metaplasia detection"
        titlePending={false}
        latestStatus="completed"
        latestStage="completed"
        runningElapsed=""
        error=""
        isLoading={false}
        isStopping={false}
        isResuming={false}
        isDeleting={false}
        canStop={false}
        canResume={false}
        canDelete={false}
        onStop={noop}
        onResume={noop}
        onDelete={noop}
      />,
    )

    expect(screen.getByTestId('autoresearch-session-detail-owner-chip')).toHaveTextContent('Yihui Wang')
  })
})
