import {
  AGGREGATORS,
  AGGREGATOR_OPTIONS,
  BACKBONE_GROUPS,
  ENCODER_OPTIONS,
  FEATURE_EXTRACTORS,
  OPTIMIZERS,
  SEGMENTATION_ARCHITECTURES,
  SEGMENTATION_BACKBONES,
  SEGMENTATION_LOSSES,
  SelectOption,
} from './training'
import {
  fetchTrainingOptions,
  TrainingAggregatorOption,
  TrainingExtractorOption,
  TrainingOptimizerOption,
  TrainingSegmentationBackboneOption,
  TrainingSegmentationLossOption,
} from '../api/trainingOptions'

const toMutableArray = <T>(value: readonly T[]): T[] => value as T[]

const replaceArray = <T>(target: readonly T[], next: readonly T[]): void => {
  const mutable = toMutableArray(target)
  mutable.splice(0, mutable.length, ...next)
}

const toExtractorSelectOptions = (extractors: readonly TrainingExtractorOption[]): SelectOption[] => (
  extractors.map((extractor) => ({
    value: extractor.id,
    label: extractor.name,
    description: extractor.description,
  }))
)

const toAggregatorSelectOptions = (aggregators: readonly TrainingAggregatorOption[]): SelectOption[] => (
  aggregators.map((aggregator) => ({
    value: aggregator.id,
    label: aggregator.name,
    description: aggregator.description,
  }))
)

const toOptimizerSelectOptions = (optimizers: readonly TrainingOptimizerOption[]): SelectOption[] => (
  optimizers.map((optimizer) => ({
    value: optimizer.value,
    label: optimizer.label,
  }))
)

const toBackboneGroups = (backbones: readonly TrainingSegmentationBackboneOption[]): string[] => (
  [...new Set(backbones.map((backbone) => backbone.group))]
)

const toSegmentationLosses = (losses: readonly TrainingSegmentationLossOption[]) => (
  losses.map((loss) => ({
    id: loss.id,
    name: loss.name,
    description: loss.description,
  }))
)

let hasAttemptedTrainingOptionsHydration = false

export async function bootstrapTrainingOptions(): Promise<void> {
  if (hasAttemptedTrainingOptionsHydration) {
    return
  }

  hasAttemptedTrainingOptionsHydration = true

  try {
    const options = await fetchTrainingOptions()

    replaceArray(FEATURE_EXTRACTORS, options.feature_extractors)
    replaceArray(ENCODER_OPTIONS, toExtractorSelectOptions(options.feature_extractors))

    replaceArray(AGGREGATORS, options.aggregators)
    replaceArray(AGGREGATOR_OPTIONS, toAggregatorSelectOptions(options.aggregators))

    replaceArray(SEGMENTATION_ARCHITECTURES, options.segmentation_architectures)
    replaceArray(SEGMENTATION_BACKBONES, options.segmentation_backbones)
    replaceArray(BACKBONE_GROUPS, toBackboneGroups(options.segmentation_backbones))

    replaceArray(SEGMENTATION_LOSSES, toSegmentationLosses(options.segmentation_losses))
    replaceArray(OPTIMIZERS, toOptimizerSelectOptions(options.optimizers))
  } catch {
  }
}
