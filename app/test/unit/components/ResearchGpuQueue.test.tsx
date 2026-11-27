import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { JobProgress } from '@renderer/components/autoresearch/ResearchResults'
import i18n from '@renderer/i18n'

vi.mock('echarts-for-react', () => ({ default: () => null }))
afterEach(cleanup)

it.each([['en-US','Waiting for GPU resources'], ['zh-CN','正在等待 GPU 资源'], ['zh-HK','正在等候 GPU 資源']])('shows a localized GPU wait notice without treating it as failure: %s', async (language, heading) => {
  await i18n.changeLanguage(language)
  render(<JobProgress events={[]} job={{job_id:'r',kind:'experiment',status:'queued',payload:{device:'gpu'},result:{},scheduling:{state:'waiting',position:2,required_vram_mb:8192,reason:'memory',wait_seconds:40}}} />)
  expect(screen.getByRole('status')).toHaveTextContent(heading)
  expect(screen.getByRole('status')).toHaveTextContent('8.0 GiB')
  expect(screen.getByRole('status')).toHaveTextContent('2')
})
