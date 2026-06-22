import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BackgroundTaskPanel } from '../../../src/renderer/src/components/BackgroundTaskPanel'
import * as backgroundTaskModule from '../../../src/renderer/src/contexts/BackgroundTaskContext'
import type { BackgroundTask, BackgroundTaskContextType } from '../../../src/renderer/src/contexts/BackgroundTaskContext'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('../../../src/renderer/src/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

describe('BackgroundTaskPanel upload cancellation', () => {
  const cancelTaskMock = vi.fn()
  const cancelServerTaskMock = vi.fn()
  const removeTaskMock = vi.fn()
  const togglePanelMock = vi.fn()
  const clearCompletedTasksMock = vi.fn()
  const unsubscribeMock = vi.fn()
  const subscribeTrainingSSEMock = vi.fn(() => unsubscribeMock)
  const subscribeAnalysisSSEMock = vi.fn(() => unsubscribeMock)
  const subscribeStorageSSEMock = vi.fn(() => unsubscribeMock)

  const uploadTask: BackgroundTask = {
    id: 'upload-task-1',
    type: 'upload',
    title: 'Uploading 1 file',
    items: [{ id: 'slide-1', name: 'slide.svs', status: 'running', progress: 25 }],
    status: 'running',
    createdAt: new Date('2026-05-14T00:00:00Z'),
    totalProgress: 25,
    successCount: 0,
    failedCount: 0,
  }

  const scanDirectoryTask: BackgroundTask = {
    id: 'scan_scan-123',
    type: 'scan_directory',
    title: 'Scan Directory (21546/0)',
    items: [{ id: 'scan-123', name: 'Scan Directory (21546/0)', status: 'running', progress: 50 }],
    status: 'running',
    createdAt: new Date('2026-05-14T00:00:00Z'),
    totalProgress: 50,
    successCount: 0,
    failedCount: 0,
    isServerTask: true,
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    cancelTaskMock.mockReset()
    cancelServerTaskMock.mockReset()
    removeTaskMock.mockReset()
    togglePanelMock.mockReset()
    clearCompletedTasksMock.mockReset()
    unsubscribeMock.mockReset()
    subscribeTrainingSSEMock.mockClear()
    subscribeAnalysisSSEMock.mockClear()
    subscribeStorageSSEMock.mockClear()

    vi.spyOn(backgroundTaskModule, 'useBackgroundTask').mockReturnValue({
      tasks: [uploadTask],
      analysisTasks: [],
      rawTrainingTasks: null,
      isProcessing: true,
      isPanelExpanded: true,
      diskSpace: null,
      metadataUploadResults: new Map(),
      cancelTask: cancelTaskMock,
      cancelServerTask: cancelServerTaskMock,
      removeTask: removeTaskMock,
      togglePanel: togglePanelMock,
      clearCompletedTasks: clearCompletedTasksMock,
      subscribeTrainingSSE: subscribeTrainingSSEMock,
      subscribeAnalysisSSE: subscribeAnalysisSSEMock,
      subscribeStorageSSE: subscribeStorageSSEMock,
    } as unknown as BackgroundTaskContextType)
  })

  it('asks for confirmation before cancelling an active upload task', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BackgroundTaskPanel />
      </MemoryRouter>,
    )

    await user.click(screen.getAllByRole('button')[1])

    expect(screen.getByText('backgroundTask.confirm')).toBeInTheDocument()
    expect(cancelTaskMock).not.toHaveBeenCalled()
  })

  it('cancels the upload task only after confirmation', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BackgroundTaskPanel />
      </MemoryRouter>,
    )

    await user.click(screen.getAllByRole('button')[1])
    await user.click(screen.getAllByRole('button', { name: '' })[1])

    expect(cancelTaskMock).toHaveBeenCalledWith('upload-task-1')
    expect(cancelServerTaskMock).not.toHaveBeenCalled()
  })

  it('renders scan_directory task with Scan Directory label instead of Delete External', async () => {
    vi.spyOn(backgroundTaskModule, 'useBackgroundTask').mockReturnValue({
      tasks: [scanDirectoryTask],
      analysisTasks: [],
      rawTrainingTasks: null,
      isProcessing: true,
      isPanelExpanded: true,
      diskSpace: null,
      metadataUploadResults: new Map(),
      cancelTask: cancelTaskMock,
      cancelServerTask: cancelServerTaskMock,
      removeTask: removeTaskMock,
      togglePanel: togglePanelMock,
      clearCompletedTasks: clearCompletedTasksMock,
      subscribeTrainingSSE: subscribeTrainingSSEMock,
      subscribeAnalysisSSE: subscribeAnalysisSSEMock,
      subscribeStorageSSE: subscribeStorageSSEMock,
    } as unknown as BackgroundTaskContextType)

    render(
      <MemoryRouter>
        <BackgroundTaskPanel />
      </MemoryRouter>,
    )

    expect(screen.getByText('backgroundTask.typeLabels.scanDirectory')).toBeInTheDocument()
    expect(screen.queryByText('backgroundTask.typeLabels.deleteExternal')).not.toBeInTheDocument()
  })
})
