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

export const organSources = [
  'Adrenal Gland', 'Aorta', 'Bladder', 'Blood Vessel', 'Bone', 'Bone Marrow',
  'Brain', 'Breast', 'Bronchus', 'Cartilage', 'Cervix', 'Colon',
  'Endometrium', 'Esophagus', 'Eye', 'Fallopian Tube', 'Gallbladder',
  'Heart', 'Joint', 'Kidney', 'Larynx', 'Liver', 'Lung', 'Lymph Node',
  'Mesentery', 'Muscle', 'Oral Cavity', 'Ovary', 'Pancreas', 'Parathyroid',
  'Penis', 'Peripheral Nerve', 'Peritoneum', 'Pharynx', 'Pituitary Gland',
  'Pleura', 'Prostate', 'Rectum', 'Retina', 'Salivary Gland', 'Skin',
  'Small Intestine', 'Soft Tissue', 'Spinal Cord', 'Spleen', 'Stomach',
  'Testis', 'Thymus', 'Thyroid', 'Tongue', 'Tonsil', 'Trachea',
  'Ureter', 'Urethra', 'Uterus', 'Vagina', 'Vulva', 'Other'
]

export const organSourceKeyMap: Record<string, string> = {
  'Adrenal Gland': 'adrenalGland',
  'Aorta': 'aorta',
  'Bladder': 'bladder',
  'Blood Vessel': 'bloodVessel',
  'Bone': 'bone',
  'Bone Marrow': 'boneMarrow',
  'Brain': 'brain',
  'Breast': 'breast',
  'Bronchus': 'bronchus',
  'Cartilage': 'cartilage',
  'Cervix': 'cervix',
  'Colon': 'colon',
  'Endometrium': 'endometrium',
  'Esophagus': 'esophagus',
  'Eye': 'eye',
  'Fallopian Tube': 'fallopianTube',
  'Gallbladder': 'gallbladder',
  'Heart': 'heart',
  'Joint': 'joint',
  'Kidney': 'kidney',
  'Larynx': 'larynx',
  'Liver': 'liver',
  'Lung': 'lung',
  'Lymph Node': 'lymphNode',
  'Mesentery': 'mesentery',
  'Muscle': 'muscle',
  'Oral Cavity': 'oralCavity',
  'Ovary': 'ovary',
  'Pancreas': 'pancreas',
  'Parathyroid': 'parathyroid',
  'Penis': 'penis',
  'Peripheral Nerve': 'peripheralNerve',
  'Peritoneum': 'peritoneum',
  'Pharynx': 'pharynx',
  'Pituitary Gland': 'pituitaryGland',
  'Pleura': 'pleura',
  'Prostate': 'prostate',
  'Rectum': 'rectum',
  'Retina': 'retina',
  'Salivary Gland': 'salivaryGland',
  'Skin': 'skin',
  'Small Intestine': 'smallIntestine',
  'Soft Tissue': 'softTissue',
  'Spinal Cord': 'spinalCord',
  'Spleen': 'spleen',
  'Stomach': 'stomach',
  'Testis': 'testis',
  'Thymus': 'thymus',
  'Thyroid': 'thyroid',
  'Tongue': 'tongue',
  'Tonsil': 'tonsil',
  'Trachea': 'trachea',
  'Ureter': 'ureter',
  'Urethra': 'urethra',
  'Uterus': 'uterus',
  'Vagina': 'vagina',
  'Vulva': 'vulva',
  'Other': 'other',
}

export const generateCaseId = () => {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let result = ''
  for (let i = 0; i < 5; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return result
}

