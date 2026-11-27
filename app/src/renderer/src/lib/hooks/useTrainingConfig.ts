/**
 * useTrainingConfig Hook
 *
 * Manages training configuration state including preprocessing and model parameters.
 * Note: tileSize and stride removed - now auto-determined by PrePATH-style tiling
 * based on WSI magnification to ensure consistent physical coverage (~128μm).
 */

import { useState } from 'react'
import {
  DEFAULT_PYRAMID_LEVEL,
  DEFAULT_FEATURE_BATCH_SIZE,
  SEGMENTATION_DEFAULTS,
  FILTER_DEFAULTS,
  TRAINING_DEFAULTS,
  SEG_TRAINING_DEFAULTS,
  SPLIT_DEFAULTS,
  DEFAULT_AGGREGATOR,
  DEFAULT_EXTRACTOR,
  DEFAULT_PATCH_CLASSIFIER,
  DEFAULT_SEG_ARCHITECTURE,
  DEFAULT_SEG_BACKBONE,
  DEFAULT_SEG_LOSS_NAMES,
  DEFAULT_SEG_LOSS_WEIGHTS,
  DEFAULT_FM_DECODER_TYPE,
  FmDecoderType,
  SplitStrategy,
} from '../../constants/training'
import { useDraftState } from './useDraftState'
import { defaultDetectionOptions, type DetectionModelOptions } from '../../components/training/DetectionModelConfig'

const D = 'draft:wizard:tc:'

export interface UseTrainingConfigReturn {
  detection: DetectionModelOptions
  setDetection: (value: DetectionModelOptions) => void
  // Preprocessing (Step 3) - tileSize and stride removed, auto-determined by PrePATH-style
  pyramidLevel: number
  setPyramidLevel: (level: number) => void
  featureExtractor: string
  setFeatureExtractor: (extractor: string) => void
  featureBatchSize: number
  setFeatureBatchSize: (size: number) => void

  // Segmentation params
  segSthresh: number
  setSegSthresh: (val: number) => void
  segMthresh: number
  setSegMthresh: (val: number) => void
  segClose: number
  setSegClose: (val: number) => void
  segUseOtsu: boolean
  setSegUseOtsu: (val: boolean) => void

  // Filter params
  filterAreaThresh: number
  setFilterAreaThresh: (val: number) => void
  filterHoleArea: number
  setFilterHoleArea: (val: number) => void
  filterMaxHoles: number
  setFilterMaxHoles: (val: number) => void

  // Model config (Step 4)
  // Classifier head (Patch-level classification)
  classifier: string
  setClassifier: (cls: string) => void

  aggregator: string
  setAggregator: (agg: string) => void
  learningRate: number
  setLearningRate: (lr: number) => void
  epochs: number
  setEpochs: (epochs: number) => void
  trainBatchSize: number
  setTrainBatchSize: (size: number) => void
  optimizer: string
  setOptimizer: (opt: string) => void
  earlyStoppingPatience: number
  setEarlyStoppingPatience: (patience: number) => void
  autoBalance: boolean
  setAutoBalance: (balance: boolean) => void

  // Segmentation training config (Step 4 for segmentation tasks)
  segArchitecture: string
  setSegArchitecture: (arch: string) => void
  segBackbone: string
  setSegBackbone: (backbone: string) => void
  segFmDecoderType: FmDecoderType
  setSegFmDecoderType: (decoder: FmDecoderType) => void
  segLossNames: string[]
  setSegLossNames: (names: string[]) => void
  segLossWeights: number[]
  setSegLossWeights: (weights: number[]) => void

  // Split config
  splitStrategy: SplitStrategy
  setSplitStrategy: (strategy: SplitStrategy) => void
  kFoldSplits: number
  setKFoldSplits: (k: number) => void
  randomSeed: number
  setRandomSeed: (seed: number) => void
  stratified: boolean
  setStratified: (value: boolean) => void
}

export function useTrainingConfig(): UseTrainingConfigReturn {
  const [detection, setDetection] = useDraftState(`${D}detection`, defaultDetectionOptions)
  const [pyramidLevel, setPyramidLevel] = useDraftState(`${D}pyramidLevel`, DEFAULT_PYRAMID_LEVEL)
  const [featureExtractor, setFeatureExtractor] = useDraftState(`${D}featureExtractor`, DEFAULT_EXTRACTOR)
  const [featureBatchSize, setFeatureBatchSize] = useDraftState(`${D}featureBatchSize`, DEFAULT_FEATURE_BATCH_SIZE)

  // Segmentation params (from localStorage or defaults)
  const [segSthresh, setSegSthresh] = useState(
    Number(localStorage.getItem('seg_sthresh') || SEGMENTATION_DEFAULTS.sthresh)
  )
  const [segMthresh, setSegMthresh] = useState(
    Number(localStorage.getItem('seg_mthresh') || SEGMENTATION_DEFAULTS.mthresh)
  )
  const [segClose, setSegClose] = useState(
    Number(localStorage.getItem('seg_close') || SEGMENTATION_DEFAULTS.close)
  )
  const [segUseOtsu, setSegUseOtsu] = useState(
    localStorage.getItem('seg_use_otsu') === 'true'
  )

  // Filter params
  const [filterAreaThresh, setFilterAreaThresh] = useState(
    Number(localStorage.getItem('filter_a_t') || FILTER_DEFAULTS.areaThresh)
  )
  const [filterHoleArea, setFilterHoleArea] = useState(
    Number(localStorage.getItem('filter_a_h') || FILTER_DEFAULTS.holeArea)
  )
  const [filterMaxHoles, setFilterMaxHoles] = useState(
    Number(localStorage.getItem('filter_max_n_holes') || FILTER_DEFAULTS.maxHoles)
  )

  const [classifier, setClassifier] = useDraftState(`${D}classifier`, DEFAULT_PATCH_CLASSIFIER)
  const [aggregator, setAggregator] = useDraftState(`${D}aggregator`, DEFAULT_AGGREGATOR)
  const [learningRate, setLearningRate] = useState(TRAINING_DEFAULTS.learningRate)
  const [epochs, setEpochs] = useState(TRAINING_DEFAULTS.epochs)
  const [trainBatchSize, setTrainBatchSize] = useState(TRAINING_DEFAULTS.batchSize)
  const [optimizer, setOptimizer] = useDraftState(`${D}optimizer`, TRAINING_DEFAULTS.optimizer)
  const [earlyStoppingPatience, setEarlyStoppingPatience] = useDraftState(`${D}earlyStoppingPatience`, TRAINING_DEFAULTS.earlyStoppingPatience)
  const [autoBalance, setAutoBalance] = useDraftState(`${D}autoBalance`, TRAINING_DEFAULTS.autoBalance)

  const [segArchitecture, setSegArchitecture] = useDraftState(`${D}segArchitecture`, DEFAULT_SEG_ARCHITECTURE)
  const [segBackbone, setSegBackbone] = useDraftState(`${D}segBackbone`, DEFAULT_SEG_BACKBONE)
  const [segFmDecoderType, setSegFmDecoderType] = useDraftState<FmDecoderType>(`${D}segFmDecoderType`, DEFAULT_FM_DECODER_TYPE)
  const [segLossNames, setSegLossNames] = useDraftState<string[]>(`${D}segLossNames`, DEFAULT_SEG_LOSS_NAMES)
  const [segLossWeights, setSegLossWeights] = useDraftState<number[]>(`${D}segLossWeights`, DEFAULT_SEG_LOSS_WEIGHTS)

  const [splitStrategy, setSplitStrategy] = useDraftState<SplitStrategy>(`${D}splitStrategy`, SPLIT_DEFAULTS.strategy)
  const [kFoldSplits, setKFoldSplits] = useDraftState(`${D}kFoldSplits`, SPLIT_DEFAULTS.kFoldSplits)
  const [randomSeed, setRandomSeed] = useDraftState(`${D}randomSeed`, SPLIT_DEFAULTS.randomSeed)
  const [stratified, setStratified] = useDraftState(`${D}stratified`, SPLIT_DEFAULTS.stratified)

  return {
    detection, setDetection,
    // Preprocessing (tileSize and stride removed - auto-determined by PrePATH-style)
    pyramidLevel,
    setPyramidLevel,
    featureExtractor,
    setFeatureExtractor,
    featureBatchSize,
    setFeatureBatchSize,

    // Segmentation
    segSthresh,
    setSegSthresh,
    segMthresh,
    setSegMthresh,
    segClose,
    setSegClose,
    segUseOtsu,
    setSegUseOtsu,

    // Filter
    filterAreaThresh,
    setFilterAreaThresh,
    filterHoleArea,
    setFilterHoleArea,
    filterMaxHoles,
    setFilterMaxHoles,

    // Model config
    classifier,
    setClassifier,
    aggregator,
    setAggregator,
    learningRate,
    setLearningRate,
    epochs,
    setEpochs,
    trainBatchSize,
    setTrainBatchSize,
    optimizer,
    setOptimizer,
    earlyStoppingPatience,
    setEarlyStoppingPatience,
    autoBalance,
    setAutoBalance,

    // Segmentation training config
    segArchitecture,
    setSegArchitecture,
    segBackbone,
    setSegBackbone,
    segFmDecoderType,
    setSegFmDecoderType,
    segLossNames,
    setSegLossNames,
    segLossWeights,
    setSegLossWeights,

    // Split config
    splitStrategy,
    setSplitStrategy,
    kFoldSplits,
    setKFoldSplits,
    randomSeed,
    setRandomSeed,
    stratified,
    setStratified,
  }
}
