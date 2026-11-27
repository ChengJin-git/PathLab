import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ListPage from '@renderer/pages/ListPage'
import { TooltipProvider } from '@renderer/components/ui/tooltip'
import * as api from '@renderer/api'
import * as wsiApi from '@renderer/api/wsi'

const state = vi.hoisted(() => ({
  error: vi.fn(), success: vi.fn(), tasks: [], deletingDatasetNames: new Set(),
  subscribeStorageSSE: () => () => {},
}))
vi.mock('@renderer/contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true, user: { id:'owner' } }) }))
vi.mock('@renderer/contexts/ToastContext', () => ({ useToast: () => state }))
vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({ useBackgroundTask: () => state }))
vi.mock('react-i18next', async original => ({
  ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t:(key: string) => key,i18n:{language:'en-US'} }),
}))

const dataset: api.DatasetSummary = {
  dataset_id:'ds',dataset_name:'Original Dataset',user_id:'owner',can_delete:true,
  data_type:'patch',task_types:['patch_classification'],aggregation_level:'file',source_organ:'Lung',
  metadata: {}, revision: 1, tasks: [],
  is_public:false,file_count:100,total_size:1000,has_predefined_splits:false,
}
const mount = () => render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
  <TooltipProvider><MemoryRouter><ListPage /></MemoryRouter></TooltipProvider>
</QueryClientProvider>)
const edit = async (container: HTMLElement) => {
  await screen.findByText('Original Dataset')
  const icon = container.querySelector('svg.lucide-pencil')!
  fireEvent.click(icon.closest('button')!)
  fireEvent.change(await screen.findByLabelText('Dataset name'),{target:{value:'Edited Dataset'}})
}

beforeEach(() => {
  vi.restoreAllMocks()
  state.success.mockClear();state.error.mockClear()
  vi.spyOn(api,'fetchDatasetSourceOptions').mockResolvedValue(['Lung'])
  vi.spyOn(wsiApi,'fetchDatasetSummary').mockResolvedValue(dataset)
})

describe('Data Repo mutation acknowledgement', () => {
  it('uses one properties request and closes with server data while reconciliation is pending',async () => {
    vi.spyOn(api,'fetchDatasets').mockResolvedValueOnce({items:[dataset],total:1})
      .mockImplementation(() => new Promise(() => {}))
    const save = vi.spyOn(wsiApi,'updateDatasetProperties').mockResolvedValue({dataset:{
      dataset_id:'ds',name:'Edited Dataset',data_type:'patch',task_types:['patch_classification'],aggregation_level:'file',source_organ:'Lung',is_public:false, metadata:{},revision:2,description:'',
    }})
    const {container} = mount()
    await edit(container)
    fireEvent.click(screen.getByRole('button',{name:'Save'}))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(save).toHaveBeenCalledWith('ds',expect.objectContaining({name:'Edited Dataset',revision:1}))
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('keeps the draft and original card when the transaction is rejected',async () => {
    vi.spyOn(api,'fetchDatasets').mockResolvedValue({items:[dataset],total:1})
    vi.spyOn(wsiApi,'updateDatasetProperties').mockRejectedValue(new Error('Invalid property combination'))
    const {container} = mount()
    await edit(container)
    fireEvent.click(screen.getByRole('button',{name:'Save'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid property combination')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('Dataset name')).toHaveValue('Edited Dataset')
    expect(screen.getByTestId('dataset-card-title')).toHaveTextContent('Original Dataset')
    expect(state.success).not.toHaveBeenCalled()
  })
})
