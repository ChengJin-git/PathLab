import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import AutoResearchClinicalSessionView from '@renderer/components/autoresearch/views/AutoResearchClinicalSessionView'
import i18n from '@renderer/i18n'
import type { AutoResearchSessionDetail } from '@renderer/types/autoresearch'

describe('AutoResearchClinicalSessionView', () => {
  beforeEach(() => {
    void i18n.changeLanguage('en-US')
  })

  afterEach(() => {
    cleanup()
    void i18n.changeLanguage('en-US')
  })

  it('shows internal and external result cards in the main clinical view', () => {
    const session: AutoResearchSessionDetail = {
      session_id: 'patch-results',
      title: 'Patch classification',
      question: 'Run patch-level classification with external validation',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      state: {
        stage: 'completed',
        objective: { success_metric: 'auc' },
        best_metric_value: 0.978,
        best_run_id: 'run_patch',
        run_history: [
          {
            iteration: 0,
            run_id: 'run_patch',
            metric_name: 'auc',
            metric_value: 0.978,
            committed: true,
            status: 'completed',
            dataset_name: 'Nanfang-GC-IM',
            metrics: {
              test: { auc: 0.978, accuracy: 0.93, n_test: 57 },
            },
          },
        ],
        external_test_history: [
          {
            run_id: 'run_external',
            status: 'completed',
            committed: true,
            dataset_name: 'PWH-GC-IM',
            metrics: { auc: 0.944, accuracy: 0.91, n_samples: 2697 },
          },
        ],
      },
      events: [],
    }

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchClinicalSessionView
          sessionId="patch-results"
          session={session}
          events={[]}
          streamStatus="closed"
          displayTitle="Patch classification"
          titlePending={false}
          latestStatus="completed"
          runningElapsed=""
          error=""
          isLoading={false}
          isStopping={false}
          isResuming={false}
          isDeleting={false}
          canStop={false}
          canResume={false}
          canDelete={false}
          onStop={() => {}}
          onResume={() => {}}
          onDelete={() => {}}
        />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('autoresearch-internal-summary')).toHaveTextContent('AUC 0.978')
    expect(screen.getByTestId('autoresearch-internal-summary')).toHaveTextContent('Nanfang-GC-IM')
    expect(screen.getByTestId('autoresearch-internal-summary')).toHaveTextContent('57 samples')
    expect(screen.getByTestId('autoresearch-external-summary')).toHaveTextContent('AUC 0.944')
    expect(screen.getByTestId('autoresearch-external-summary')).toHaveTextContent('PWH-GC-IM')
    expect(screen.getByTestId('autoresearch-external-summary')).toHaveTextContent('2697 samples')
  })
})
