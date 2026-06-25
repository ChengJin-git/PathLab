import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import IterationLadder from '@renderer/components/autoresearch/IterationLadder'
import type {
  AutoResearchIterationView,
  AutoResearchSessionMetadataView,
  AutoResearchToolView,
} from '@renderer/lib/autoresearchEventSelectors'

const sessionMetadata: AutoResearchSessionMetadataView = {
  taskType: 'slide-level classification',
  foundationModel: 'Virchow2',
  milMethod: 'ABMIL',
}

describe('IterationLadder', () => {
  it('shows human ratchet labels instead of leaking the internal info status', () => {
    const iterations: AutoResearchIterationView[] = [
      { index: 1, status: 'success', metricName: 'auc', metricValue: 0.94, committed: true, runId: 'run_a', tools: [] },
      { index: 2, status: 'info', metricName: 'auc', metricValue: 0.91, committed: false, runId: 'run_b', tools: [] },
    ]

    render(
      <IterationLadder
        iterations={iterations}
        bestMetric={{ name: 'auc', value: 0.94, runId: 'run_a' }}
        sessionMetadata={sessionMetadata}
        toolCards={[]}
        sessionId="s1"
      />,
    )

    expect(screen.getByText('committed')).toBeInTheDocument()
    expect(screen.getByText('not committed')).toBeInTheDocument()
    expect(screen.queryByText(/^info$/i)).not.toBeInTheDocument()
  })

  it('keeps the right column natural-height so only the execution console scrolls', () => {
    const iterations: AutoResearchIterationView[] = Array.from({ length: 5 }, (_, index) => ({
      index: index + 1,
      status: index < 2 ? 'success' : 'info',
      metricName: 'auc',
      metricValue: 0.9 + index / 100,
      committed: index < 2,
      runId: `run_${index}`,
      tools: [],
    }))
    const toolCards: AutoResearchToolView[] = Array.from({ length: 14 }, (_, index) => ({
      id: `tool-${index}`,
      tool: `tool_${index}`,
      iteration: index % 5,
      status: 'success',
      summary: `tool ${index}`,
      stage: 'execution',
      events: [],
    }))

    render(
      <IterationLadder
        iterations={iterations}
        bestMetric={{ name: 'auc', value: 0.94, runId: 'run_4' }}
        sessionMetadata={sessionMetadata}
        toolCards={toolCards}
        sessionId="s1"
      />,
    )

    expect(screen.getByTestId('autoresearch-sidebar')).not.toHaveClass('xl:overflow-y-auto')
    expect(screen.getByTestId('autoresearch-sidebar')).not.toHaveClass('xl:overflow-hidden')
    expect(screen.getByTestId('autoresearch-sidebar')).not.toHaveClass('xl:h-full')
    expect(screen.getByTestId('autoresearch-iteration-ladder-card')).toHaveClass('xl:min-h-[320px]')
    expect(screen.getByTestId('autoresearch-iteration-ladder-card')).not.toHaveClass('xl:flex-1')
    expect(screen.getByTestId('autoresearch-iteration-ladder-card')).not.toHaveClass('xl:overflow-hidden')
    expect(screen.getByTestId('autoresearch-iteration-ladder-scroll')).not.toHaveClass('xl:overflow-y-auto')
    expect(screen.getByTestId('autoresearch-tools-card')).not.toHaveClass('xl:mt-auto')
    expect(screen.getByTestId('autoresearch-tools-list')).not.toHaveClass('xl:overflow-y-auto')
    expect(screen.getByText('+10 more tools')).toBeInTheDocument()
  })

  it('hides terminal error badges on the currently running iteration until it finishes', () => {
    const iterations: AutoResearchIterationView[] = [
      { index: 1, status: 'error', metricName: 'auc', tools: [] },
    ]

    const { rerender } = render(
      <IterationLadder
        iterations={iterations}
        bestMetric={null}
        sessionMetadata={sessionMetadata}
        toolCards={[]}
        currentIteration={1}
        maxIterations={1}
        isRunning
      />,
    )

    expect(screen.getByTestId('autoresearch-ladder-running-strip')).toHaveTextContent('Iter 1/1 running')
    expect(screen.getByText('Running iteration')).toBeInTheDocument()
    expect(screen.queryByText(/^error$/i)).not.toBeInTheDocument()

    rerender(
      <IterationLadder
        iterations={iterations}
        bestMetric={null}
        sessionMetadata={sessionMetadata}
        toolCards={[]}
        currentIteration={1}
        maxIterations={1}
        isRunning={false}
      />,
    )

    expect(screen.getByText(/^error$/i)).toBeInTheDocument()
  })

  it('shows live training epoch progress in the running strip and current iteration', () => {
    const iterations: AutoResearchIterationView[] = [
      { index: 1, status: 'info', metricName: 'auc', metricValue: 0.91, tools: [] },
    ]

    render(
      <IterationLadder
        iterations={iterations}
        bestMetric={{ name: 'auc', value: 0.9683, runId: 'run_b' }}
        sessionMetadata={sessionMetadata}
        toolCards={[]}
        currentIteration={1}
        maxIterations={1}
        isRunning
        trainingProgress={{
          current_epoch: 10,
          total_epochs: 30,
          current_val_auc: 0.9567,
          best_val_auc: 0.9683,
        }}
      />,
    )

    const runningStrip = screen.getByTestId('autoresearch-ladder-running-strip')
    expect(runningStrip).toHaveTextContent('Iter 1/1 running')
    expect(runningStrip).toHaveTextContent('Epoch 10/30')

    const trainingPill = screen.getByTestId('autoresearch-ladder-training-progress')
    expect(trainingPill).toHaveTextContent('Epoch 10/30')
    expect(trainingPill).toHaveTextContent('AUC 0.957')
    expect(trainingPill).toHaveTextContent('best 0.968')
  })
})
