/**
 * Training Components Index
 *
 * Export all training-related components for easy imports.
 */

// Step Components
export { TaskSetupStep } from './TaskSetupStep'
export { DataSelectionStep } from './DataSelectionStep'
export { PreprocessingStep } from './PreprocessingStep'
export { ModelConfigStep } from './ModelConfigStep'
export { ReviewSubmitStep } from './ReviewSubmitStep'
export { TaskResultStep } from './TaskResultStep'

// Shared Components
export { StepProgressBar } from './StepProgressBar'
export { WSIDataTable } from './WSIDataTable'
export { DataSplitConfig } from './DataSplitConfig'
export { RegistrationProgress } from './RegistrationProgress'

// Modal Components
export { DeleteConfirmModal } from './DeleteConfirmModal'
export { EditMetadataModal } from './EditMetadataModal'
export { BatchEditModal } from './BatchEditModal'
export { FileMetadataModal } from './FileMetadataModal'

// Re-export types from individual components
export type { DataSelectionStepProps, DatasetInfo, WSIItem } from './DataSelectionStep'
export type { WSIDataTableProps } from './WSIDataTable'
export type { DataSplitConfigProps } from './DataSplitConfig'
export type { RegistrationProgressProps } from './RegistrationProgress'
export type { DeleteConfirmModalProps, WSIDeleteInfo } from './DeleteConfirmModal'
export type { EditMetadataModalProps, WSIEditInfo } from './EditMetadataModal'
export type { BatchEditModalProps } from './BatchEditModal'
export type { FileMetadataModalProps } from './FileMetadataModal'

