import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import IterationLadder from '@renderer/components/pathscientist/IterationLadder'
import type {
  PathScientistIterationView,
  PathScientistSessionMetadataView,
  PathScientistToolView,
} from '@renderer/lib/pathscientistEventSelectors'

const sessionMetadata: PathScientistSessionMetadataView = {
  taskType: 'slide-level classification',
  foundationModel: 'Virchow2',
  milMethod: 'ABMIL',
}

describe('IterationLadder', () => {
  it('shows human ratchet labels instead of leaking the internal info status', () => {
    const iterations: PathScientistIterationView[] = [
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
    const iterations: PathScientistIterationView[] = Array.from({ length: 5 }, (_, index) => ({
      index: index + 1,
      status: index < 2 ? 'success' : 'info',
      metricName: 'auc',
      metricValue: 0.9 + index / 100,
      committed: index < 2,
      runId: `run_${index}`,
      tools: [],
    }))
    const toolCards: PathScientistToolView[] = Array.from({ length: 14 }, (_, index) => ({
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

    expect(screen.getByTestId('pathscientist-sidebar')).not.toHaveClass('xl:overflow-y-auto')
    expect(screen.getByTestId('pathscientist-sidebar')).not.toHaveClass('xl:overflow-hidden')
    expect(screen.getByTestId('pathscientist-sidebar')).not.toHaveClass('xl:h-full')
    expect(screen.getByTestId('pathscientist-iteration-ladder-card')).toHaveClass('xl:min-h-[320px]')
    expect(screen.getByTestId('pathscientist-iteration-ladder-card')).not.toHaveClass('xl:flex-1')
    expect(screen.getByTestId('pathscientist-iteration-ladder-card')).not.toHaveClass('xl:overflow-hidden')
    expect(screen.getByTestId('pathscientist-iteration-ladder-scroll')).not.toHaveClass('xl:overflow-y-auto')
    expect(screen.getByTestId('pathscientist-tools-card')).not.toHaveClass('xl:mt-auto')
    expect(screen.getByTestId('pathscientist-tools-list')).not.toHaveClass('xl:overflow-y-auto')
    expect(screen.getByText('+10 more tools')).toBeInTheDocument()
  })
})
