import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import ResearchHandoffCard from '@renderer/components/chat/ResearchHandoffCard'
import type { ResearchHandoff } from '@renderer/api/chat'
import type { AutoResearchSessionSummary } from '@renderer/types/autoresearch'
import i18n from '@renderer/i18n'

afterEach(cleanup)
const card = (handoff: ResearchHandoff, streaming = true, status?: string) => <MemoryRouter>
  <ResearchHandoffCard handoff={handoff} streaming={streaming} session={status ? {status, title: 'BCFC 安全分流'} as AutoResearchSessionSummary : undefined} />
</MemoryRouter>

it('keeps a labelled status through preparation, submission and the saved receipt', async () => {
  await i18n.changeLanguage('zh-CN')
  const view = render(card({status: 'preparing'}))
  expect(screen.getByRole('status')).toHaveTextContent('正在准备任务')
  expect(screen.getByText(/整理研究目标、数据引用/)).toBeInTheDocument()
  expect(view.container.querySelector('.animate-pulse')).toBeNull()
  view.rerender(card({status: 'submitting', task_kind: 'analysis'}))
  expect(screen.getByRole('status')).toHaveTextContent('正在提交后台')
  const receipt: ResearchHandoff = {status: 'accepted', session_id: 'saved-task', session_status: 'queued', task_kind: 'analysis'}
  view.rerender(card(receipt, false))
  expect(screen.getByText(/后台队列/)).toBeInTheDocument()
  expect(screen.getByRole('link', {name: '查看任务'})).toHaveAttribute('href', '/autoresearch/sessions/saved-task')
  view.rerender(card(receipt, false, 'running'))
  expect(screen.getByText(/后台继续执行/)).toBeInTheDocument()
  expect(screen.getByText('BCFC 安全分流')).toBeInTheDocument()
  view.unmount()
  render(card(receipt, false, 'completed'))
  expect(screen.getByText(/查看结果/)).toBeInTheDocument()
  expect(screen.getByRole('link', {name: '查看任务'})).toBeInTheDocument()
})

it('retains failures and turns interrupted loading into a retryable status', async () => {
  await i18n.changeLanguage('zh-CN')
  const view = render(card({status: 'failed', error: '研究队列已满'}, false))
  expect(screen.getByRole('status')).toHaveTextContent('任务未启动')
  expect(screen.getByText('研究队列已满')).toBeInTheDocument()
  expect(screen.getByText(/已创建的任务会复用/)).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  view.rerender(card({status: 'preparing'}, false))
  expect(screen.getByRole('status')).toHaveTextContent('任务交接已中断')
  expect(view.container.querySelector('.animate-spin')).toBeNull()
})

it.each([['en-US', 'Preparing task'], ['zh-HK', '正在準備任務']])('localizes the status in %s', async (language, label) => {
  await i18n.changeLanguage(language)
  render(card({status: 'preparing'}))
  expect(screen.getByRole('status')).toHaveTextContent(label)
})
