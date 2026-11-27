import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ChatQuickActions from '@renderer/components/chat/ChatQuickActions'
import i18n from '@renderer/i18n'

afterEach(cleanup)

it('distinguishes autonomous research from concrete chat actions', async () => {
  await i18n.changeLanguage('zh-CN')
  const scenario = vi.fn(), research = vi.fn()
  render(<ChatQuickActions centered canResearch onScenario={scenario} onResearch={research} />)
  fireEvent.click(screen.getByRole('button', { name: '训练模型' }))
  expect(scenario).toHaveBeenCalledWith(expect.objectContaining({ id: 'train-model' }))
  fireEvent.click(screen.getByRole('button', { name: /自主探索/ }))
  expect(research).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: '自动实验' })).not.toBeInTheDocument()
})

it('offers an expandable shortcut group in a conversation and respects read-only mode', async () => {
  await i18n.changeLanguage('zh-CN')
  render(<ChatQuickActions centered={false} canResearch={false} onScenario={vi.fn()} onResearch={vi.fn()} />)
  const toggle = screen.getByRole('button', { name: '快捷入口' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.queryByRole('button', { name: /自主探索/ })).not.toBeInTheDocument()
})
