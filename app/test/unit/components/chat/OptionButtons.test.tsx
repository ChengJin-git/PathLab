import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@renderer/i18n'

import { OptionButtons, parseOptions } from '@renderer/components/chat/OptionButtons'
import { sanitizeConfigBlocksForAI } from '@renderer/lib/utils/chatMessageParser'

describe('OptionButtons', () => {
  beforeEach(async () => { await i18n.changeLanguage('zh-CN') })
  it('does not silently discard valid model choices based on words in their names', () => {
    expect(parseOptions('[OPTIONS]\n- All Models Baseline\n- 查看所有分类模型\n[/OPTIONS]')).toEqual([
      { text: 'All Models Baseline' }, { text: '查看所有分类模型' },
    ])
  })
  it('renders real dataset choices and sends the clicked label intact into follow-up history', async () => {
    const content = '请选择数据集：\n[OPTIONS]\n- Gastric Cohort（胃，WSI）\n- Colon Patches（结肠，patch）\n- 注册新数据\n[/OPTIONS]'
    const onSelect = vi.fn()
    render(<OptionButtons options={parseOptions(content)!} onSelect={onSelect} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Colon Patches（结肠，patch）' }))
    expect(onSelect).toHaveBeenCalledWith('Colon Patches（结肠，patch）')
    expect(sanitizeConfigBlocksForAI(content)).toBe(content)
  })
  it('does not allow selecting options while a response is still generating', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()

    render(
      <OptionButtons
        options={[{ text: '阅读全文' }]}
        onSelect={onSelect}
        disabled
      />,
    )

    await user.click(screen.getByRole('button', { name: '阅读全文' }))
    await user.click(screen.getByRole('button', { name: '我有其他要求' }))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()

    expect(onSelect).not.toHaveBeenCalled()
  })

  it.each([
    ['dataset', ['唯一工作区数据集']],
    ['model', ['Model A', 'Model B']],
    ['mode', ['内部验证', '外部验证']],
    ['label', ['Tumor', 'Normal']],
    ['recovery', ['补充标注', '查看数据']],
    ['many tasks', ['Task A', 'Task B', 'Task C', 'Task D', 'Task E', 'Task F']],
  ])('supports an actual custom request for %s without submitting a placeholder', async (_, labels) => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<OptionButtons options={labels.map(text => ({ text }))} onSelect={onSelect} />)
    await user.click(screen.getByRole('button', { name: '我有其他要求' }))
    expect(onSelect).not.toHaveBeenCalled()
    const input = screen.getByRole('textbox', { name: '告诉我你的其他选择或要求' })
    expect(input).toHaveFocus()
    expect(screen.getByRole('button', { name: '发送要求' })).toBeDisabled()
    await user.type(input, '先解释限制，不要执行')
    await user.click(screen.getByRole('button', { name: '发送要求' }))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith('先解释限制，不要执行')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('keeps composition, cancellation and loading from sending a custom request', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    const options = [{ text: 'Only Dataset' }]
    const view = render(<OptionButtons options={options} onSelect={onSelect} />)
    await user.click(screen.getByRole('button', { name: '我有其他要求' }))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '选择其他数据集' } })
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
    expect(onSelect).not.toHaveBeenCalled()
    view.rerender(<OptionButtons options={options} onSelect={onSelect} disabled />)
    expect(input).toBeDisabled()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).not.toHaveBeenCalled()
    view.rerender(<OptionButtons options={options} onSelect={onSelect} />)
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(onSelect).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '我有其他要求' }))
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith('选择其他数据集')
  })

  it.each([
    ['zh-CN', '我有其他要求', '发送要求'],
    ['zh-HK', '我有其他要求', '傳送要求'],
    ['en-US', 'I have another request', 'Send request'],
  ])('localizes the fallback and editor in %s', async (language, label, send) => {
    await act(async () => { await i18n.changeLanguage(language) })
    render(<OptionButtons options={[{ text: 'Dataset A' }]} onSelect={vi.fn()} />)
    await userEvent.setup().click(screen.getByRole('button', { name: label }))
    expect(screen.getByRole('button', { name: send })).toBeDisabled()
  })
})
