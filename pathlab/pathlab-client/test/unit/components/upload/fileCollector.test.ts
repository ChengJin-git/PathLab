import { describe, it, expect, vi } from 'vitest'
import { collectItemsFromDataTransfer } from '@renderer/components/upload'

type FakeFileEntry = {
  isFile: true
  isDirectory: false
  name: string
  file: (success: (file: File) => void, failure?: () => void) => void
}

type FakeDirectoryEntry = {
  isFile: false
  isDirectory: true
  name: string
  createReader: () => {
    readEntries: (success: (entries: Array<FakeFileEntry | FakeDirectoryEntry>) => void, failure?: () => void) => void
  }
}

function makeFile(name: string, content = name): File {
  return new File([content], name, { lastModified: 1 })
}

function makeFileEntry(file: File): FakeFileEntry {
  return {
    isFile: true,
    isDirectory: false,
    name: file.name,
    file: (success) => success(file),
  }
}

function makeDirectoryEntry(
  name: string,
  entries: Array<FakeFileEntry | FakeDirectoryEntry>,
  batchSize = 1,
): FakeDirectoryEntry {
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => {
      let index = 0
      return {
        readEntries: (success) => {
          const next = entries.slice(index, index + batchSize)
          index += batchSize
          success(next)
        },
      }
    },
  }
}

function makeDataTransfer(entries: Array<FakeFileEntry | FakeDirectoryEntry>): DataTransfer {
  const items = entries.map(entry => ({
    webkitGetAsEntry: () => entry,
  }))

  return {
    items,
    files: [],
  } as unknown as DataTransfer
}

describe('collectItemsFromDataTransfer', () => {
  it('reports incremental folder collection progress while traversing nested files', async () => {
    const mainFile = makeFile('case-a.mrxs')
    const folder = makeDirectoryEntry('case-a', [
      makeFileEntry(makeFile('tile-1.dat')),
      makeFileEntry(makeFile('tile-2.dat')),
      makeDirectoryEntry('nested', [
        makeFileEntry(makeFile('tile-3.dat')),
      ]),
    ])
    const dataTransfer = makeDataTransfer([makeFileEntry(mainFile), folder])
    const onProgress = vi.fn()

    const result = await Reflect.apply(collectItemsFromDataTransfer, undefined, [
      dataTransfer,
      { onProgress, yieldAfterEntries: 1 },
    ])

    expect(result.items).toHaveLength(1)
    expect(result.items[0]?.name).toBe('case-a.mrxs')
    expect(result.items[0]?.associatedFiles).toHaveLength(3)
    expect(onProgress).toHaveBeenCalled()

    const snapshots = onProgress.mock.calls.map(([snapshot]) => snapshot)

    expect(snapshots.some(snapshot => snapshot.phase === 'collecting')).toBe(true)
    expect(snapshots.some(snapshot => snapshot.discoveredFiles >= 2)).toBe(true)

    const finalSnapshot = snapshots.at(-1)
    expect(finalSnapshot).toMatchObject({
      phase: 'complete',
      discoveredFiles: 4,
      processedItems: 1,
      totalTopLevelEntries: 2,
      completed: true,
    })
  })
})
