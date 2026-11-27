import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PdfParsingStatus, PdfParsingCompletedCard } from '@renderer/components/chat/SearchingStatus'

vi.mock('react-i18next', () => ({ useTranslation: () => ({
  t: (key: string) => key, i18n: { language: 'zh-CN' },
}) }))

afterEach(cleanup)
const article = { url: 'https://arxiv.org/abs/2407.18449', title: 'GPFM' }

describe('article progress', () => {
  it('shows actual pages, elapsed time and an early long-document hint', () => {
    render(<PdfParsingStatus items={[{ ...article, status: 'parsing', pages_done: 21, total_pages: 73, elapsed_ms: 9000 }]} />)
    expect(screen.getByRole('status')).toHaveTextContent('已读取 21 / 73 页')
    expect(screen.getByRole('status')).toHaveTextContent('已用时 9 秒')
    expect(screen.getByRole('status')).toHaveTextContent('可随时点击停止')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '29')
  })

  it('shows received bytes without inventing a percentage for unknown size', () => {
    render(<PdfParsingStatus items={[{ ...article, status: 'downloading', bytes_received: 2 * 1024 * 1024, elapsed_ms: 10000 }]} />)
    expect(screen.getByRole('status')).toHaveTextContent('2.0 MB')
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('distinguishes queue, OCR and parsing timeout', () => {
    const { rerender } = render(<PdfParsingStatus items={[{ ...article, status: 'waiting' }]} />)
    expect(screen.getByRole('status')).toHaveTextContent('已为你短暂排队')
    rerender(<PdfParsingStatus items={[{ ...article, status: 'parsing', phase: 'ocr', pages_done: 1, total_pages: 4 }]} />)
    expect(screen.getByRole('status')).toHaveTextContent('正在识别扫描页文字')
    rerender(<PdfParsingCompletedCard items={[{ ...article, status: 'parse_failed', error_code: 'parse_timeout' }]} />)
    expect(screen.getByText('PDF 已下载，正文解析超时')).toBeInTheDocument()
  })

  it('shows a verified failure and practical recovery after a saved conversation reload', async () => {
    render(<PdfParsingCompletedCard items={[{...article, status:'download_failed', action:'download', error_code:'not_found', message:'文档下载未完成：来源不存在或已被移除。', recovery_hint:'请核对原链接，或上传原始文档。'}]} />)
    await waitFor(() => expect(screen.getByText('文档下载未完成：来源不存在或已被移除。')).toBeVisible())
    expect(screen.getByText('请核对原链接，或上传原始文档。')).toBeVisible()
    expect(screen.queryByText(/登录|验证码|paywall/)).toBeNull()
  })
})
