import { isSupportedName, isTmapDataFile, getBaseName, getFilePath } from '../../constants/fileTypes'
import type {
  LocalItem,
  MrxsDataFolder,
  CollectionResult,
  CollectItemsOptions,
  CollectionProgressPhase,
  CollectionProgressSnapshot,
} from './types'

export const buildFileKey = (file: File) => `${file.name}-${file.size}-${file.lastModified}`

type CollectorProgressState = Omit<CollectionProgressSnapshot, 'phase'>

type CollectorContext = {
  state: CollectorProgressState
  onProgress?: (snapshot: CollectionProgressSnapshot) => void
  yieldAfterEntries: number
  pendingYieldEntries: number
}

const DEFAULT_YIELD_AFTER_ENTRIES = 50

const yieldToBrowser = async (): Promise<void> => {
  await new Promise<void>(resolve => {
    setTimeout(resolve, 0)
  })
}

const emitProgress = (
  context: CollectorContext,
  phase: CollectionProgressPhase,
  overrides: Partial<CollectorProgressState> = {}
) => {
  context.onProgress?.({
    phase,
    ...context.state,
    ...overrides,
  })
}

const maybeYield = async (context: CollectorContext, phase: CollectionProgressPhase) => {
  context.pendingYieldEntries += 1
  if (context.pendingYieldEntries < context.yieldAfterEntries) {
    return
  }

  context.pendingYieldEntries = 0
  emitProgress(context, phase)
  await yieldToBrowser()
}

const readAllEntries = async (directoryEntry: any): Promise<any[]> => {
  const reader = directoryEntry.createReader()
  const entries: any[] = []
  while (true) {
    const batch: any[] = await new Promise(resolve => reader.readEntries(resolve, () => resolve([])))
    if (!batch.length) break
    entries.push(...batch)
  }
  return entries
}

// Recursively collect all files from a directory (for MRXS data folders)
const collectAllFilesFromDirectory = async (directoryEntry: any, context: CollectorContext): Promise<File[]> => {
  const entries = await readAllEntries(directoryEntry)
  const files: File[] = []
  for (const entry of entries) {
    if (entry.isFile) {
      const file = await new Promise<File | null>(resolve => {
        entry.file((f: File) => resolve(f), () => resolve(null))
      })
      if (file) {
        files.push(file)
        context.state.discoveredFiles += 1
        emitProgress(context, 'collecting', { currentDirectoryName: directoryEntry.name })
      }
    } else if (entry.isDirectory) {
      context.state.discoveredDirectories += 1
      emitProgress(context, 'collecting', { currentDirectoryName: entry.name })
      const subFiles = await collectAllFilesFromDirectory(entry, context)
      files.push(...subFiles)
    }

    await maybeYield(context, 'collecting')
  }
  return files
}

export const collectItemsFromDataTransfer = async (
  dataTransfer: DataTransfer,
  options: CollectItemsOptions = {}
): Promise<CollectionResult> => {
  const dataItems = Array.from(dataTransfer.items || [])
  const hasEntries = dataItems.some(item => (item as any).webkitGetAsEntry)
  const context: CollectorContext = {
    state: {
      totalTopLevelEntries: 0,
      processedItems: 0,
      discoveredFiles: 0,
      discoveredDirectories: 0,
      currentDirectoryName: undefined,
      completed: false,
    },
    onProgress: options.onProgress,
    yieldAfterEntries: Math.max(1, options.yieldAfterEntries ?? DEFAULT_YIELD_AFTER_ENTRIES),
    pendingYieldEntries: 0,
  }

  emitProgress(context, 'preparing')

  // First-level files (WSI candidates) and sub-folders (MRXS data only)
  const firstLevelFiles: File[] = []
  const mrxsDataFolders: MrxsDataFolder[] = []
  // Track directly dragged folders (potential MRXS data folders dragged separately)
  const directlyDraggedFolders: MrxsDataFolder[] = []

  if (hasEntries) {
    const topEntries = dataItems.map(item => (item as any).webkitGetAsEntry?.()).filter(Boolean)
    context.state.totalTopLevelEntries = topEntries.length
    emitProgress(context, 'collecting')

    for (const entry of topEntries) {
      if (entry.isFile) {
        const file = await new Promise<File | null>(resolve => {
          entry.file((f: File) => resolve(f), () => resolve(null))
        })
        if (file) {
          firstLevelFiles.push(file)
          context.state.discoveredFiles += 1
          emitProgress(context, 'collecting', { currentDirectoryName: undefined })
        }
      } else if (entry.isDirectory) {
        context.state.discoveredDirectories += 1
        emitProgress(context, 'collecting', { currentDirectoryName: entry.name })
        const folderEntries = await readAllEntries(entry)
        const hasWsiFiles = folderEntries.some(e => e.isFile && isSupportedName(e.name))

        if (hasWsiFiles) {
          for (const subEntry of folderEntries) {
            if (subEntry.isFile) {
              const file = await new Promise<File | null>(resolve => {
                subEntry.file((f: File) => resolve(f), () => resolve(null))
              })
              if (file) {
                firstLevelFiles.push(file)
                context.state.discoveredFiles += 1
                emitProgress(context, 'collecting', { currentDirectoryName: entry.name })
              }
            } else if (subEntry.isDirectory) {
              context.state.discoveredDirectories += 1
              emitProgress(context, 'collecting', { currentDirectoryName: subEntry.name })
              const subFolderFiles = await collectAllFilesFromDirectory(subEntry, context)
              mrxsDataFolders.push({
                folderName: subEntry.name,
                folderFiles: subFolderFiles
              })
            }

            await maybeYield(context, 'collecting')
          }
        } else {
          const folderFiles = await collectAllFilesFromDirectory(entry, context)
          directlyDraggedFolders.push({
            folderName: entry.name,
            folderFiles
          })
        }

        context.state.processedItems += 1
        emitProgress(context, 'collecting', { currentDirectoryName: entry.name })
      }

      await maybeYield(context, 'collecting')
    }
  } else {
    const files = Array.from(dataTransfer.files || [])
    context.state.totalTopLevelEntries = files.length
    firstLevelFiles.push(...files)
    context.state.discoveredFiles = files.length
    emitProgress(context, 'collecting', { currentDirectoryName: undefined })
  }

  const files = firstLevelFiles
  const folders = [...mrxsDataFolders, ...directlyDraggedFolders]

  const mrxsFiles = files.filter(f => f.name.toLowerCase().endsWith('.mrxs'))
  const tmapFiles = files.filter(f => f.name.toLowerCase().endsWith('.tmap'))
  const dtFiles = files.filter(f => isTmapDataFile(f.name))

  const result: LocalItem[] = []
  const usedFiles = new Set<File>()
  const usedFolders = new Set<string>()
  const unsupportedFileNames: string[] = []

  const isElectron = files.length > 0 && files.some(f => getFilePath(f))

  emitProgress(context, 'matching', { currentDirectoryName: undefined })

  // MRXS
  for (const mrxsFile of mrxsFiles) {
    const baseName = getBaseName(mrxsFile.name)
    const matchingFolder = folders.find(f => f.folderName.toLowerCase() === baseName.toLowerCase())
    usedFiles.add(mrxsFile)
    if (matchingFolder) usedFolders.add(matchingFolder.folderName)

    const hasAssociated = !!matchingFolder && matchingFolder.folderFiles.length > 0

    if (isElectron) {
      const path = getFilePath(mrxsFile)!
      result.push({
        key: path, name: mrxsFile.name, path, type: 'mrxs',
        associatedPaths: matchingFolder ? [] : undefined,
        missingAssociated: !hasAssociated
      })
    } else {
      result.push({
        key: buildFileKey(mrxsFile), name: mrxsFile.name, file: mrxsFile, type: 'mrxs',
        associatedFiles: matchingFolder?.folderFiles || [],
        missingAssociated: !hasAssociated
      })
    }
  }

  // TMAP
  for (const tmapFile of tmapFiles) {
    const baseName = getBaseName(tmapFile.name)
    const matchingDtFiles = dtFiles.filter(f => getBaseName(f.name) === baseName)
    usedFiles.add(tmapFile)
    matchingDtFiles.forEach(f => usedFiles.add(f))

    if (isElectron) {
      const path = getFilePath(tmapFile)!
      result.push({
        key: path, name: tmapFile.name, path, type: 'tmap',
        associatedPaths: matchingDtFiles.map(f => getFilePath(f)!).filter(Boolean)
      })
    } else {
      result.push({
        key: buildFileKey(tmapFile), name: tmapFile.name, file: tmapFile, type: 'tmap',
        associatedFiles: matchingDtFiles
      })
    }
  }

  // Collect JSON files separately (for segmentation mask matching)
  const jsonFiles: File[] = []

  // Standard
  for (const file of files) {
    if (usedFiles.has(file)) continue
    if (isTmapDataFile(file.name)) continue
    // Separate JSON files for potential mask matching
    if (file.name.toLowerCase().endsWith('.json')) {
      jsonFiles.push(file)
      continue
    }
    if (!isSupportedName(file.name)) {
      unsupportedFileNames.push(file.name)
      continue
    }
    if (isElectron) {
      const path = getFilePath(file)!
      result.push({ key: path, name: file.name, path, type: 'standard' })
    } else {
      result.push({ key: buildFileKey(file), name: file.name, file, type: 'standard' })
    }
  }

  // Collect orphan folders (MRXS data folders without matching .mrxs)
  const orphanFolders = folders.filter(f => !usedFolders.has(f.folderName))

  // Collect orphan dt files (without matching .tmap)
  const orphanDtFiles = new Map<string, File[]>()
  for (const dtFile of dtFiles) {
    if (usedFiles.has(dtFile)) continue
    const baseName = getBaseName(dtFile.name)
    if (!orphanDtFiles.has(baseName)) {
      orphanDtFiles.set(baseName, [])
    }
    orphanDtFiles.get(baseName)!.push(dtFile)
  }

  context.state.completed = true
  context.state.currentDirectoryName = undefined
  emitProgress(context, 'complete')

  return { items: result, orphanFolders, orphanDtFiles, unsupportedFileNames, jsonFiles }
}
