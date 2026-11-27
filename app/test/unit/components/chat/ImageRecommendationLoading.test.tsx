import { act, render, waitFor, cleanup, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ImageRecommendationCard } from '@renderer/components/chat/ImageRecommendationCard'
import { fetchRecommendedImages, fetchAllWSIList, fetchAllResults, fetchAvailableHeatmaps } from '@renderer/api'
import { setWorkspaceSelection, resetWorkspaceSelection } from '@renderer/lib/workspaceSelection'
import { setAuthToken } from '@renderer/api/client'

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@renderer/api', () => ({
  fetchRecommendedImages: vi.fn(), fetchAllWSIList: vi.fn(), fetchAllResults: vi.fn(),
  fetchAvailableHeatmaps: vi.fn(), getRecommendationThumbnailUrl: () => '/preview',
  getRecommendationPatchCAMImageUrl: () => '/cam', getRecommendationHeatmapThumbnailUrl: () => '/heatmap',
  getRecommendationSegMaskImageUrl: () => '/mask', getLabelThumbnailUrl: () => '/label', getWSILabels: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  resetWorkspaceSelection()
  setAuthToken('image-test-' + Math.random())
  vi.mocked(fetchRecommendedImages).mockResolvedValue({ items: [] })
})
afterEach(cleanup)

describe('bounded image recommendation loading', () => {
  it('makes one filtered request instead of loading a full dataset/results inventory', async () => {
    render(<ImageRecommendationCard recommendation={{ query: 'show some images from the dataset', max_count: 3,
      filters: { dataset_id: 'ds_1', label: 'Tumor', correct_prediction: false, event_status: 0 },
    }} />)
    await waitFor(() => expect(fetchRecommendedImages).toHaveBeenCalledTimes(1))
    expect(fetchRecommendedImages).toHaveBeenCalledWith(expect.objectContaining({
      dataset_id: 'ds_1', label: 'Tumor', correct_prediction: false, event_status: 0, limit: 3,
    }))
    expect(fetchAllWSIList).not.toHaveBeenCalled()
    expect(fetchAllResults).not.toHaveBeenCalled()
    expect(fetchAvailableHeatmaps).not.toHaveBeenCalled()
  })

  it('revalidates candidate access after a workspace switch', async () => {
    const recommendation = { query: 'test scope switch', max_count: 3 }
    render(<ImageRecommendationCard recommendation={recommendation} />)
    await waitFor(() => expect(fetchRecommendedImages).toHaveBeenCalledTimes(1))
    act(() => setWorkspaceSelection({ workspaceId: 'another', executionMode: 'standard', expertId: null, enabledSkills: null, enabledConnectors: null }))
    await waitFor(() => expect(fetchRecommendedImages).toHaveBeenCalledTimes(2))
  })

  it('rechecks revoked access when the card is remounted instead of reusing cached candidates', async () => {
    const recommendation = { query: 'permission test', filters: { dataset_id: 'granted' }, max_count: 3 }
    const view = render(<ImageRecommendationCard recommendation={recommendation} />)
    await waitFor(() => expect(fetchRecommendedImages).toHaveBeenCalledTimes(1))
    view.unmount()
    vi.mocked(fetchRecommendedImages).mockRejectedValueOnce(new Error('Access revoked'))
    render(<ImageRecommendationCard recommendation={recommendation} />)
    await waitFor(() => expect(screen.getByText('chatComponents.imageRecommendation.failedToLoad')).toBeInTheDocument())
    expect(fetchRecommendedImages).toHaveBeenCalledTimes(2)
    expect(fetchAllWSIList).not.toHaveBeenCalled()
  })
})
