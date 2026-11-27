import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResearchOutline from '@renderer/components/autoresearch/ResearchOutline'
import { researchPlanState, researchStepStatus } from '@renderer/components/autoresearch/researchPlan'
import i18n from '@renderer/i18n'

afterEach(cleanup)

describe('adaptive task plan', () => {
  it('counts only recorded work and reports parallel active steps', async () => {
    const plan = [
      {id: 'evidence', title: 'Review literature', status: 'completed'},
      {id: 'cohorts', title: 'Check public cohorts', status: 'running'},
      {id: 'methods', title: 'Compare methods', status: 'running'},
      {id: 'delivery', title: 'Write the review', status: 'pending'},
    ]
    expect(researchPlanState(plan, 'running')).toMatchObject({completed: 1, total: 4})
    expect(researchPlanState(plan, 'running').active).toHaveLength(2)
    await i18n.changeLanguage('zh-CN')
    const onSelect = vi.fn()
    render(<ResearchOutline plan={plan} selected="methods" onSelect={onSelect} status="running" completedRuns={0} totalRuns={0} />)
    expect(screen.getByRole('heading', {name: '任务计划'})).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '已完成 1 / 4 项已记录步骤')
    expect(screen.queryByText('构思')).not.toBeInTheDocument()
    expect(screen.queryByText('实验')).not.toBeInTheDocument()
    const selected = screen.getByRole('button', {name: /Compare methods/})
    expect(selected).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(selected)
    expect(onSelect).toHaveBeenCalledWith('methods')
    expect(researchStepStatus('running', 'paused')).toBe('paused')
    expect(researchStepStatus('running', 'interrupted')).toBe('interrupted')
  })
})
