import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import en from '@renderer/locales/en-US.json'
import { StorageInventoryPanel } from '@renderer/components/settings/storage/StorageInventoryPanel'
import * as api from '@renderer/api/storage'

vi.mock('@renderer/api/storage', () => ({
  getStorageInventory: vi.fn(), getInventoryItems: vi.fn(), cleanStorageInventory: vi.fn(),
  scanStorageInventory: vi.fn(), cancelInventoryOperation: vi.fn(),
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, values: Record<string, unknown> = {}) => {
    const value = key.split('.').reduce((item: any, part) => item?.[part], en)
    return String(value ?? key).replace(/{{(\w+)}}/g, (_, name) => String(values[name] ?? ''))
  } }),
}))

const generation = 'a'.repeat(32)
const snapshot: api.StorageInventory = {
  generation, scanned_at: 1700000000, size: 10000, allocated: 10000, files: 1000000, links: 0, operation: null,
  categories: [{ category: 'features', size: 10000, allocated: 10000, files: 1000000, links: 0,
    items: 1000000, reclaimable: 10000, orphaned: 10000, cached: 0, states: {
      orphaned: { items: 1000000, allocated: 10000 }, cached: { items: 0, allocated: 0 },
      referenced: { items: 0, allocated: 0 }, recent: { items: 0, allocated: 0 }, managed: { items: 0, allocated: 0 },
    } }],
}
const page = (offset = 0): api.InventoryPage => ({
  generation, total: 1000000, allocated: 10000, next_cursor: offset ? null : '100:next',
  items: Array.from({ length: 50 }, (_, i) => ({
    id: String(offset + i), path: `features/uni/hash/slide-${offset + i}.pt`, category: 'features', owner: '',
    state: 'orphaned', reason: 'unreferenced', allocated: 100, size: 100, files: 1, links: 0,
  })),
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getStorageInventory).mockResolvedValue(snapshot)
  vi.mocked(api.getInventoryItems).mockImplementation(async (_category, _state, cursor) => page(cursor ? 50 : 0))
  vi.mocked(api.cleanStorageInventory).mockResolvedValue({ id: 'cleanup', kind: 'storage_cleanup', status: 'completed', processed: 0, total: 0, result: null, error: null })
})

describe('storage selection scopes', () => {
  it('shows terabytes and has no database housekeeping section', async () => {
    vi.mocked(api.getStorageInventory).mockResolvedValue({
      ...snapshot,
      allocated: 4002.33 * 1024 ** 3,
      categories: snapshot.categories.map(category => ({ ...category, allocated: 2536.44 * 1024 ** 3 })),
    })
    render(<StorageInventoryPanel showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)
    expect(await screen.findByText('3.91 TB')).toBeVisible()
    expect(screen.getByText('2.48 TB')).toBeVisible()
    expect(screen.queryByText('Database housekeeping')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check' })).not.toBeInTheDocument()
  })

  it('hides page ranges until loaded and offers a localized retry after a page failure', async () => {
    const user = userEvent.setup()
    let rejectPage!: (error: Error) => void
    vi.mocked(api.getInventoryItems).mockImplementationOnce(() => new Promise((_, reject) => { rejectPage = reject }))
    const { container } = render(<StorageInventoryPanel showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)
    await screen.findByLabelText('Loading files')
    expect(container.querySelector('[data-storage-pagination]')).toBeNull()
    await act(async () => rejectPage(new Error('Internal Server Error')))
    expect(await screen.findByText('Could not load files.')).toBeVisible()
    expect(screen.queryByText('Internal Server Error')).not.toBeInTheDocument()
    expect(container.querySelector('[data-storage-pagination]')).toBeNull()
    expect(screen.getByRole('button', { name: 'Clean up' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('slide-0.pt')
    expect(container.querySelector('[data-storage-pagination]')).toHaveTextContent('1–50 of 1,000,000')
    expect(api.getInventoryItems).toHaveBeenCalledTimes(2)
  })

  it('shows empty state without a 1–0 range and omits a zero progress count', async () => {
    vi.mocked(api.getStorageInventory).mockResolvedValue({ ...snapshot, operation: {
      id: 'scan', kind: 'storage_scan', status: 'processing', processed: 0, total: 0,
      result: { stage: 'references' }, error: null,
    } })
    vi.mocked(api.getInventoryItems).mockResolvedValue({ generation, total: 0, allocated: 0, items: [], next_cursor: null })
    const { container } = render(<StorageInventoryPanel showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)
    expect(await screen.findByText('No files in this group.')).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('Checking references')
    expect(screen.getByRole('status')).not.toHaveTextContent('0 processed')
    expect(container.querySelector('[data-storage-pagination]')).toBeNull()
  })

  it('starts with no selection and submits only this page after explicit selection', async () => {
    const user = userEvent.setup()
    const confirm = vi.fn()
    const { container } = render(<StorageInventoryPanel showConfirmDialog={confirm} closeConfirmDialog={vi.fn()} />)
    await screen.findByText('slide-0.pt')
    expect(container.querySelector('select')).toBeNull()
    expect(screen.getByRole('button', { name: 'Clean up' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Selection options' }))
    await user.click(screen.getByRole('menuitem', { name: /Select this page/ }))
    expect(screen.getByText('50 selected')).toBeVisible()
    expect(screen.getAllByRole('checkbox', { checked: true })).toHaveLength(51)
    await user.click(screen.getByRole('button', { name: 'Clean up' }))
    await confirm.mock.calls[0][0].onConfirm()
    await waitFor(() => expect(api.cleanStorageInventory).toHaveBeenCalledWith({
      generation, category: undefined, state: 'orphaned', scope: 'selected', ids: Array.from({ length: 50 }, (_, i) => String(i)),
    }))
  })

  it('keeps all-filtered selection across pages with individual exclusions, without loading all IDs', async () => {
    const user = userEvent.setup()
    const confirm = vi.fn()
    render(<StorageInventoryPanel showConfirmDialog={confirm} closeConfirmDialog={vi.fn()} />)
    await screen.findByText('slide-0.pt')
    await user.click(screen.getByRole('button', { name: 'Selection options' }))
    await user.click(screen.getByRole('menuitem', { name: /Select all/ }))
    expect(screen.getByText('1,000,000 selected across all pages')).toBeVisible()
    await user.click(screen.getByRole('checkbox', { name: 'Select features/uni/hash/slide-0.pt' }))
    expect(screen.getByRole('checkbox', { name: 'Select this page' })).toBePartiallyChecked()
    await user.click(screen.getByRole('button', { name: 'Next page' }))
    await screen.findByText('slide-50.pt')
    expect(screen.getByRole('checkbox', { name: 'Select features/uni/hash/slide-50.pt' })).toBeChecked()
    expect(screen.getByText('999,999 selected across all pages')).toBeVisible()
    expect(api.getInventoryItems).toHaveBeenCalledTimes(2)
    await user.click(screen.getByRole('button', { name: 'Clean selected' }))
    expect(confirm.mock.calls[0][0].message).toContain('across all pages')
    await confirm.mock.calls[0][0].onConfirm()
    await waitFor(() => expect(api.cleanStorageInventory).toHaveBeenCalledWith({
      generation, category: undefined, state: 'orphaned', scope: 'all', excluded_ids: ['0'],
    }))
  })

  it('clears selection on filter changes and makes protected rows read-only', async () => {
    const user = userEvent.setup()
    render(<StorageInventoryPanel showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)
    await screen.findByText('slide-0.pt')
    await user.click(screen.getByRole('checkbox', { name: 'Select this page' }))
    await user.click(screen.getByRole('button', { name: 'File status' }))
    await user.click(screen.getByRole('option', { name: 'In use' }))
    await waitFor(() => expect(screen.queryByRole('checkbox')).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Selection options' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'File status' }))
    await user.click(screen.getByRole('option', { name: 'Unreferenced files' }))
    await screen.findByRole('checkbox', { name: 'Select this page' })
    expect(screen.getByRole('button', { name: 'Clean up' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Selection options' }))
    expect(within(screen.getByRole('menu')).queryByRole('menuitem', { name: 'Clear selection' })).not.toBeInTheDocument()
  })
})
