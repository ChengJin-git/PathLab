/**
 * Metrics Constants
 *
 * Centralized configuration for evaluation metrics, charts, and display settings.
 * Extracted from various components for better maintainability.
 */

// ============================================================================
// Metric Definitions
// ============================================================================

export interface MetricDefinition {
  id: string
  label: string
  description: string
}

/**
 * Classification metrics available for model evaluation.
 */
export const CLASSIFICATION_METRICS: readonly MetricDefinition[] = [
  { id: 'accuracy', label: 'Accuracy', description: 'Overall prediction accuracy' },
  { id: 'precision', label: 'Precision', description: 'Positive predictive value' },
  { id: 'sensitivity', label: 'Sensitivity', description: 'True positive rate' },
  { id: 'specificity', label: 'Specificity', description: 'True negative rate' },
  { id: 'f1', label: 'F1 Score', description: 'Harmonic mean of precision and recall' },
  { id: 'auc', label: 'AUC', description: 'Area under ROC curve' }
] as const

/**
 * Survival analysis metrics.
 */
export const SURVIVAL_METRICS: readonly MetricDefinition[] = [
  { id: 'c_index', label: 'C-Index', description: 'Concordance index for survival prediction' },
  { id: 'integrated_brier_score', label: 'IBS', description: 'Integrated Brier Score (lower is better)' }
] as const

// ============================================================================
// Chart Definitions
// ============================================================================

export interface ChartDefinition {
  id: string
  label: string
  description: string
}

/**
 * Charts available for classification tasks.
 */
export const CLASSIFICATION_CHARTS: readonly ChartDefinition[] = [
  { id: 'confusion_matrix', label: 'Confusion Matrix', description: 'Prediction vs ground truth matrix' },
  { id: 'roc_curve', label: 'ROC Curve', description: 'Receiver operating characteristic curve' },
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs' }
] as const

/**
 * Charts available for survival analysis tasks.
 */
export const SURVIVAL_CHARTS: readonly ChartDefinition[] = [
  { id: 'km_curve', label: 'KM Curve', description: 'Kaplan-Meier survival curve' },
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs' }
] as const

/**
 * Charts for external validation (no training, so no loss curve).
 */
export const EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS: readonly ChartDefinition[] = [
  { id: 'confusion_matrix', label: 'Confusion Matrix', description: 'Prediction vs ground truth matrix' },
  { id: 'roc_curve', label: 'ROC Curve', description: 'Receiver operating characteristic curve' }
] as const

export const EXTERNAL_VALIDATION_SURVIVAL_CHARTS: readonly ChartDefinition[] = [
  { id: 'km_curve', label: 'KM Curve', description: 'Kaplan-Meier survival curve' }
] as const

// ============================================================================
// Metric Display Styling
// ============================================================================

/**
 * Tailwind CSS color classes for different metric types.
 */
export const METRIC_COLORS: Record<string, string> = {
  accuracy: 'text-blue-600 bg-blue-50 border-blue-200',
  auc: 'text-purple-600 bg-purple-50 border-purple-200',
  f1: 'text-green-600 bg-green-50 border-green-200',
  precision: 'text-amber-600 bg-amber-50 border-amber-200',
  recall: 'text-teal-600 bg-teal-50 border-teal-200',
  sensitivity: 'text-teal-600 bg-teal-50 border-teal-200',
  specificity: 'text-orange-600 bg-orange-50 border-orange-200',
  c_index: 'text-indigo-600 bg-indigo-50 border-indigo-200',
  integrated_brier_score: 'text-emerald-600 bg-emerald-50 border-emerald-200',
  loss: 'text-red-600 bg-red-50 border-red-200',
}

/**
 * Abbreviated metric names for mobile/compact display.
 */
export const METRIC_ABBREVIATIONS: Record<string, string> = {
  accuracy: 'ACC',
  precision: 'PREC',
  recall: 'REC',
  sensitivity: 'SENS',
  specificity: 'SPEC',
  f1: 'F1',
  auc: 'AUC',
  tp: 'TP',
  fp: 'FP',
  fn: 'FN',
  tn: 'TN',
  balanced_accuracy: 'B.ACC',
  mcc: 'MCC',
  support: 'SUPP',
  brier_score: 'BRIER',
  c_index: 'C-INDEX',
  integrated_brier_score: 'IBS',
}

/**
 * Metrics that should NOT be displayed as percentages (raw values).
 */
export const RAW_VALUE_METRICS = new Set([
  'loss', 'train_loss', 'val_loss', 'test_loss',
  'c_index', 'integrated_brier_score', 
  'mse', 'rmse', 'mae',
  'log_loss', 'cross_entropy',
])

// ============================================================================
// Default Selections
// ============================================================================

/**
 * Default metrics to show for classification tasks.
 */
export const DEFAULT_CLASSIFICATION_METRICS = ['accuracy', 'precision', 'sensitivity', 'f1', 'auc', 'specificity']

/**
 * Default charts to show for classification tasks.
 */
export const DEFAULT_CLASSIFICATION_CHARTS = ['confusion_matrix', 'roc_curve', 'loss_curve']

/**
 * Default metrics to show for survival tasks.
 */
export const DEFAULT_SURVIVAL_METRICS = ['c_index', 'integrated_brier_score']

/**
 * Default charts to show for survival tasks.
 */
export const DEFAULT_SURVIVAL_CHARTS = ['km_curve', 'loss_curve']

/**
 * Default charts for external validation classification (no loss_curve since no training).
 */
export const DEFAULT_EXTERNAL_CLASSIFICATION_CHARTS = ['confusion_matrix', 'roc_curve']

/**
 * Default charts for external validation survival (no loss_curve since no training).
 */
export const DEFAULT_EXTERNAL_SURVIVAL_CHARTS = ['km_curve']

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Check if a metric should be displayed as a percentage.
 */
export function isPercentageMetric(metricName: string): boolean {
  const normalizedName = metricName.toLowerCase().replace('macro_', '')
  return !RAW_VALUE_METRICS.has(normalizedName)
}

/**
 * Format metric name for display (remove prefixes, capitalize).
 */
export function formatMetricName(name: string): string {
  return name
    .replace('macro_', '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, l => l.toUpperCase())
}

/**
 * Format metric value based on whether it's a percentage or raw value.
 */
export function formatMetricValue(value: number, metricName: string): string {
  if (isPercentageMetric(metricName)) {
    return `${(value * 100).toFixed(2)}%`
  }
  return value.toFixed(4)
}

