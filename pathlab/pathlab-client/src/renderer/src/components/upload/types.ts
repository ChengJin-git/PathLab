// Upload mode type is re-exported from TaskType (classification, survival, or segmentation)
export type { TaskType as UploadMode } from '../../constants/training'
// Aggregation level type: case (case-level grouping) or file (file-level, each file independent)
export type DataLevel = 'case' | 'file'
// Data type: wsi (whole slide images) or patch (image patches/tiles)
export type DataType = 'wsi' | 'patch'

export interface LocalItem {
  key: string
  name: string
  path?: string
  file?: File
  associatedFiles?: File[]
  associatedPaths?: string[]
  type?: 'mrxs' | 'tmap' | 'standard'
  missingAssociated?: boolean  // True if MRXS/TMAP is missing associated data
}

// Metadata type with all possible fields
export interface FileMetadata {
  label: string
  case_id: string
  age: string
  gender: string
  // Survival analysis fields
  event_time: string
  event_status: string
}

export const defaultMetadata: FileMetadata = {
  label: '',
  case_id: '',
  age: '',
  gender: '',
  event_time: '',
  event_status: ''
}

export interface ElectronFilesApi {
  selectFiles?: (options?: { title?: string; filters?: { name: string; extensions: string[] }[] }) => Promise<string[] | null>
}

export interface ElectronApi {
  files?: ElectronFilesApi
}

export interface MrxsDataFolder {
  folderName: string
  folderFiles: File[]
}

export interface CollectionResult {
  items: LocalItem[]
  orphanFolders: MrxsDataFolder[]  // Folders without matching .mrxs
  orphanDtFiles: Map<string, File[]>  // baseName -> dt files without matching .tmap
  unsupportedFileNames: string[]
  jsonFiles: File[]  // JSON files collected for segmentation mask matching
}

export type CollectionProgressPhase = 'preparing' | 'collecting' | 'matching' | 'complete'

export interface CollectionProgressSnapshot {
  phase: CollectionProgressPhase
  totalTopLevelEntries: number
  processedItems: number
  discoveredFiles: number
  discoveredDirectories: number
  currentDirectoryName?: string
  completed: boolean
}

export interface CollectItemsOptions {
  onProgress?: (snapshot: CollectionProgressSnapshot) => void
  yieldAfterEntries?: number
}


export const generateCaseId = () => {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let result = ''
  for (let i = 0; i < 5; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return result
}
