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

function makePlainFileDataTransfer(files: File[]): DataTransfer {
  return {
    items: [],
    files,
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

  it('throttles progress calls for large collections so they are far fewer than file count', async () => {
    const fileCount = 55
    const entries: Array<FakeFileEntry | FakeDirectoryEntry> = []
    for (let i = 0; i < fileCount; i++) {
      entries.push(makeFileEntry(makeFile(`img-${i}.png`)))
    }
    const dataTransfer = makeDataTransfer(entries)
    const onProgress = vi.fn()

    const result = await Reflect.apply(collectItemsFromDataTransfer, undefined, [
      dataTransfer,
      { onProgress, yieldAfterEntries: 10 },
    ])

    expect(result.items).toHaveLength(fileCount)

    const progressCalls = onProgress.mock.calls.map(([snapshot]) => snapshot)
    const collectingCalls = progressCalls.filter(s => s.phase === 'collecting')

    expect(collectingCalls.length).toBeLessThan(fileCount / 2)

    const finalSnapshot = progressCalls.at(-1)
    expect(finalSnapshot).toMatchObject({
      phase: 'complete',
      discoveredFiles: fileCount,
      totalTopLevelEntries: fileCount,
      completed: true,
    })
  })

  it('emits an immediate collecting snapshot for plain file drops without entries', async () => {
    const files = [makeFile('a.png'), makeFile('b.png'), makeFile('c.png')]
    const dataTransfer = makePlainFileDataTransfer(files)
    const onProgress = vi.fn()

    const result = await Reflect.apply(collectItemsFromDataTransfer, undefined, [
      dataTransfer,
      { onProgress, yieldAfterEntries: 10 },
    ])

    expect(result.items).toHaveLength(3)

    const progressCalls = onProgress.mock.calls.map(([snapshot]) => snapshot)
    const collectingCalls = progressCalls.filter(s => s.phase === 'collecting')
    expect(collectingCalls.length).toBeGreaterThanOrEqual(1)
    expect(collectingCalls.some(s => s.discoveredFiles === 3)).toBe(true)

    const finalSnapshot = progressCalls.at(-1)
    expect(finalSnapshot).toMatchObject({
      phase: 'complete',
      discoveredFiles: 3,
      totalTopLevelEntries: 3,
      completed: true,
    })
  })
})
