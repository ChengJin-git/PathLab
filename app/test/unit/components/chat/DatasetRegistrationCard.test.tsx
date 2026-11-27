import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import { DatasetRegistrationCard, parseDatasetRegistrationConfig } from '@renderer/components/chat/DatasetRegistrationCard'

function Location() { const location = useLocation(); return <pre data-testid="location">{JSON.stringify({ path: location.pathname, state: location.state })}</pre> }
describe('Chat registration handoff', () => {
  it('carries multiple task selections and metadata to the shared upload workflow', () => {
    const config = { dataset_name: 'Cytology', data_type: 'patch' as const, task_types: ['patch_classification' as const, 'patch_detection' as const], metadata: { stain: 'H&E' }, description: 'Provided description' }
    render(<MemoryRouter><DatasetRegistrationCard config={config} /><Location /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button'))
    expect(JSON.parse(screen.getByTestId('location').textContent!)).toEqual({ path: '/upload', state: expect.objectContaining({ taskTypes: config.task_types, metadata: config.metadata, description: config.description }) })
  })
  it('opens label append for an existing dataset without uploading duplicate images', () => {
    render(<MemoryRouter><DatasetRegistrationCard config={{dataset_id:'d',data_type:'wsi',task_types:['wsi_classification','wsi_survival'],initial_tab:'labels'}} /><Location /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button'))
    expect(JSON.parse(screen.getByTestId('location').textContent!).state).toMatchObject({datasetId:'d',initialTab:'labels'})
  })
  it('rejects malformed and incompatible task configurations', () => {
    expect(parseDatasetRegistrationConfig('[DATASET_REGISTRATION]{"data_type":"wsi","task_types":["patch_detection"]}[/DATASET_REGISTRATION]')).toBeNull()
    expect(parseDatasetRegistrationConfig('[DATASET_REGISTRATION]{"data_type":"patch","task_types":["patch_detection"]}[/DATASET_REGISTRATION]')?.task_types).toEqual(['patch_detection'])
  })
})
