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
  labelKey: string
  descriptionKey: string
}

/**
 * Classification metrics available for model evaluation.
 */
export const CLASSIFICATION_METRICS: readonly MetricDefinition[] = [
  { id: 'accuracy', label: 'Accuracy', description: 'Overall prediction accuracy', labelKey: 'resultsPage.metricLabels.accuracy', descriptionKey: 'resultsPage.metricDescriptions.accuracy' },
  { id: 'precision', label: 'Precision', description: 'Positive predictive value', labelKey: 'resultsPage.metricLabels.precision', descriptionKey: 'resultsPage.metricDescriptions.precision' },
  { id: 'sensitivity', label: 'Sensitivity', description: 'True positive rate', labelKey: 'resultsPage.metricLabels.sensitivity', descriptionKey: 'resultsPage.metricDescriptions.sensitivity' },
  { id: 'specificity', label: 'Specificity', description: 'True negative rate', labelKey: 'resultsPage.metricLabels.specificity', descriptionKey: 'resultsPage.metricDescriptions.specificity' },
  { id: 'f1', label: 'F1 Score', description: 'Harmonic mean of precision and recall', labelKey: 'resultsPage.metricLabels.f1', descriptionKey: 'resultsPage.metricDescriptions.f1' },
  { id: 'auc', label: 'AUC', description: 'Area under ROC curve', labelKey: 'resultsPage.metricLabels.auc', descriptionKey: 'resultsPage.metricDescriptions.auc' }
] as const

/**
 * Survival analysis metrics.
 */
export const SURVIVAL_METRICS: readonly MetricDefinition[] = [
  { id: 'c_index', label: 'C-Index', description: 'Concordance index for survival prediction', labelKey: 'resultsPage.metricLabels.c_index', descriptionKey: 'resultsPage.metricDescriptions.c_index' },
  { id: 'integrated_brier_score', label: 'IBS', description: 'Integrated Brier Score (lower is better)', labelKey: 'resultsPage.metricLabels.ibs', descriptionKey: 'resultsPage.metricDescriptions.ibs' }
] as const

/**
 * Segmentation metrics available for model evaluation.
 * Matches backend SegmentationTrainer._compute_metrics() output.
 */
export const SEGMENTATION_METRICS: readonly MetricDefinition[] = [
  { id: 'iou', label: 'IoU', description: 'Intersection over Union (Jaccard Index)', labelKey: 'resultsPage.metricLabels.iou', descriptionKey: 'resultsPage.metricDescriptions.iou' },
  { id: 'miou', label: 'mIoU', description: 'Mean Intersection over Union across segmentation classes', labelKey: 'resultsPage.metricLabels.miou', descriptionKey: 'resultsPage.metricDescriptions.miou' },
  { id: 'dice', label: 'Dice', description: 'Dice coefficient (F1 for segmentation)', labelKey: 'resultsPage.metricLabels.dice', descriptionKey: 'resultsPage.metricDescriptions.dice' },
  { id: 'accuracy', label: 'Accuracy', description: 'Pixel-level accuracy', labelKey: 'resultsPage.metricLabels.accuracy', descriptionKey: 'resultsPage.metricDescriptions.accuracy' },
  { id: 'precision', label: 'Precision', description: 'Pixel-level precision', labelKey: 'resultsPage.metricLabels.precision', descriptionKey: 'resultsPage.metricDescriptions.precision' },
  { id: 'recall', label: 'Recall', description: 'Pixel-level recall (sensitivity)', labelKey: 'resultsPage.metricLabels.recall', descriptionKey: 'resultsPage.metricDescriptions.recall' },
  { id: 'f1', label: 'F1 Score', description: 'Harmonic mean of precision and recall', labelKey: 'resultsPage.metricLabels.f1', descriptionKey: 'resultsPage.metricDescriptions.f1' },
] as const

// ============================================================================
// Chart Definitions
// ============================================================================

export interface ChartDefinition {
  id: string
  label: string
  description: string
  labelKey: string
  descriptionKey: string
}

/**
 * Charts available for classification tasks.
 */
export const CLASSIFICATION_CHARTS: readonly ChartDefinition[] = [
  { id: 'confusion_matrix', label: 'Confusion Matrix', description: 'Prediction vs ground truth matrix', labelKey: 'resultsPage.chartLabels.confusion_matrix', descriptionKey: 'resultsPage.chartDescriptions.confusion_matrix' },
  { id: 'roc_curve', label: 'ROC Curve', description: 'Receiver operating characteristic curve', labelKey: 'resultsPage.chartLabels.roc_curve', descriptionKey: 'resultsPage.chartDescriptions.roc_curve' },
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs', labelKey: 'resultsPage.chartLabels.loss_curve', descriptionKey: 'resultsPage.chartDescriptions.loss_curve' }
] as const

/**
 * Charts available for survival analysis tasks.
 */
export const SURVIVAL_CHARTS: readonly ChartDefinition[] = [
  { id: 'km_curve', label: 'KM Curve', description: 'Kaplan-Meier survival curve', labelKey: 'resultsPage.chartLabels.km_curve', descriptionKey: 'resultsPage.chartDescriptions.km_curve' },
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs', labelKey: 'resultsPage.chartLabels.loss_curve', descriptionKey: 'resultsPage.chartDescriptions.loss_curve' }
] as const

/**
 * Charts available for segmentation tasks.
 */
export const SEGMENTATION_CHARTS: readonly ChartDefinition[] = [
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs', labelKey: 'resultsPage.chartLabels.loss_curve', descriptionKey: 'resultsPage.chartDescriptions.loss_curve' },
  { id: 'iou_curve', label: 'IoU Curve', description: 'IoU score over epochs', labelKey: 'resultsPage.chartLabels.iou_curve', descriptionKey: 'resultsPage.chartDescriptions.iou_curve' },
  { id: 'dice_curve', label: 'Dice Curve', description: 'Dice score over epochs', labelKey: 'resultsPage.chartLabels.dice_curve', descriptionKey: 'resultsPage.chartDescriptions.dice_curve' },
] as const

/**
 * Charts for external validation (no training, so no loss curve).
 */
export const EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS: readonly ChartDefinition[] = [
  { id: 'confusion_matrix', label: 'Confusion Matrix', description: 'Prediction vs ground truth matrix', labelKey: 'resultsPage.chartLabels.confusion_matrix', descriptionKey: 'resultsPage.chartDescriptions.confusion_matrix' },
  { id: 'roc_curve', label: 'ROC Curve', description: 'Receiver operating characteristic curve', labelKey: 'resultsPage.chartLabels.roc_curve', descriptionKey: 'resultsPage.chartDescriptions.roc_curve' }
] as const

export const EXTERNAL_VALIDATION_SURVIVAL_CHARTS: readonly ChartDefinition[] = [
  { id: 'km_curve', label: 'KM Curve', description: 'Kaplan-Meier survival curve', labelKey: 'resultsPage.chartLabels.km_curve', descriptionKey: 'resultsPage.chartDescriptions.km_curve' }
] as const

export const EXTERNAL_VALIDATION_SEGMENTATION_CHARTS: readonly ChartDefinition[] = [
  { id: 'per_class_iou', label: 'Per-Class IoU', description: 'Per-class IoU distribution across the validation set', labelKey: 'resultsPage.chartLabels.per_class_iou', descriptionKey: 'resultsPage.chartDescriptions.per_class_iou' },
  { id: 'per_class_dice', label: 'Per-Class Dice', description: 'Per-class Dice distribution across the validation set', labelKey: 'resultsPage.chartLabels.per_class_dice', descriptionKey: 'resultsPage.chartDescriptions.per_class_dice' },
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
  // Segmentation-specific metrics
  iou: 'text-cyan-600 bg-cyan-50 border-cyan-200',
  miou: 'text-cyan-700 bg-cyan-50 border-cyan-300',
  dice: 'text-violet-600 bg-violet-50 border-violet-200',
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
  // Segmentation-specific
  iou: 'IoU',
  miou: 'mIoU',
  dice: 'DICE',
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
 * Default metrics to show for segmentation tasks.
 */
export const DEFAULT_SEGMENTATION_METRICS = ['iou', 'dice', 'accuracy', 'precision', 'recall', 'f1']

/**
 * Default charts to show for segmentation tasks.
 */
export const DEFAULT_SEGMENTATION_CHARTS = ['loss_curve', 'iou_curve', 'dice_curve']

/**
 * Default charts for external validation classification (no loss_curve since no training).
 */
export const DEFAULT_EXTERNAL_CLASSIFICATION_CHARTS = ['confusion_matrix', 'roc_curve']

/**
 * Default charts for external validation survival (no loss_curve since no training).
 */
export const DEFAULT_EXTERNAL_SURVIVAL_CHARTS = ['km_curve']

/**
 * Default charts for external validation segmentation (no loss_curve since no training).
 */
export const DEFAULT_EXTERNAL_SEGMENTATION_CHARTS = ['per_class_iou', 'per_class_dice']

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
  if (name === 'miou') return 'mIoU'
  if (name === 'iou') return 'IoU'
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

export function getSegmentationMetrics(numClasses = 1): readonly MetricDefinition[] {
  return SEGMENTATION_METRICS.filter(metric => (numClasses > 1 ? metric.id !== 'iou' : metric.id !== 'miou'))
}

export function getDefaultSegmentationMetrics(numClasses = 1): string[] {
  const primaryMetric = numClasses > 1 ? 'miou' : 'iou'
  return [primaryMetric, 'dice', 'accuracy', 'precision', 'recall', 'f1']
}

