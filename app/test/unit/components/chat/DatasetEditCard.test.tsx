import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DatasetEditCard from '@renderer/components/chat/DatasetEditCard'
import * as wsi from '@renderer/api/wsi'
import * as catalog from '@renderer/api/datasetCatalog'

vi.mock('react-i18next', async original => ({ ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ i18n: { language: 'en-US' }, t: (key: string) => key }) }))
const dataset: wsi.DatasetSummary = { dataset_id:'d', dataset_name:'Cohort', user_id:'owner', data_type:'wsi', aggregation_level:'file',
  task_types:['wsi_classification'], tasks:[], metadata:{institution:'Source',stain:'H&E'}, revision:3, file_count:2, total_size:100 }
const config = { dataset_id:'d', summary:'Add follow-up labels and record the time unit.',
  properties:{ task_types:['wsi_classification' as const,'wsi_survival' as const], metadata:{time_unit:'months'} },
  rows:[{filename:'a.svs',event_time:0,event_status:0}] }
const mount = () => render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><DatasetEditCard config={config}/></QueryClientProvider>)

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(wsi,'fetchDatasetSummary').mockResolvedValue(dataset)
})
describe('Chat dataset edit transaction', () => {
  it('submits metadata and task labels atomically, retaining source metadata and zero outcomes', async () => {
    const save = vi.spyOn(catalog,'importDatasetLabels').mockResolvedValue({dataset:{} as wsi.UpdatedDatasetProperties,updated_images:1})
    mount()
    await waitFor(() => expect(screen.getByRole('button',{name:'Save'})).toBeEnabled())
    fireEvent.click(screen.getByRole('button',{name:'Save'}))
    await screen.findByRole('button',{name:'Saved'})
    expect(save).toHaveBeenCalledExactlyOnceWith('d', {
      revision:3, properties:{...config.properties,metadata:{institution:'Source',stain:'H&E',time_unit:'months'}},
      task_types:config.properties.task_types,rows:config.rows,annotations:{},
    })
  })
  it('shows a rejected edit without claiming it was saved', async () => {
    vi.spyOn(catalog,'importDatasetLabels').mockRejectedValue(new Error('Dataset changed; reload before saving'))
    mount()
    await waitFor(() => expect(screen.getByRole('button',{name:'Save'})).toBeEnabled())
    fireEvent.click(screen.getByRole('button',{name:'Save'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('Dataset changed')
    expect(screen.queryByRole('button',{name:'Saved'})).not.toBeInTheDocument()
  })
})
