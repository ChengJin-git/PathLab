/**
 * useTrainingConfig Hook
 *
 * Manages training configuration state including preprocessing and model parameters.
 */

import { useState, useMemo } from 'react'
import {
  DEFAULT_TILE_SIZE,
  DEFAULT_STRIDE,
  DEFAULT_PYRAMID_LEVEL,
  DEFAULT_FEATURE_BATCH_SIZE,
  SEGMENTATION_DEFAULTS,
  FILTER_DEFAULTS,
  TRAINING_DEFAULTS,
  SPLIT_DEFAULTS,
  DEFAULT_AGGREGATOR,
} from '../constants/training'
import { SplitStrategy, ConfigurationValidation, KFoldValidation, RandomSplitValidation } from '../types/training'

export interface UseTrainingConfigReturn {
  // Preprocessing (Step 3)
  tileSize: number
  setTileSize: (size: number) => void
  stride: number
  setStride: (stride: number) => void
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

  // Split config
  splitStrategy: SplitStrategy
  setSplitStrategy: (strategy: SplitStrategy) => void
  kFoldSplits: number
  setKFoldSplits: (k: number) => void
  randomSeed: number
  setRandomSeed: (seed: number) => void
}

export function useTrainingConfig(): UseTrainingConfigReturn {
  // Preprocessing (Step 3)
  const [tileSize, setTileSize] = useState(DEFAULT_TILE_SIZE)
  const [stride, setStride] = useState(DEFAULT_STRIDE)
  const [pyramidLevel, setPyramidLevel] = useState(DEFAULT_PYRAMID_LEVEL)
  const [featureExtractor, setFeatureExtractor] = useState('resnet50')
  const [featureBatchSize, setFeatureBatchSize] = useState(DEFAULT_FEATURE_BATCH_SIZE)

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

  // Model config (Step 4)
  const [aggregator, setAggregator] = useState(DEFAULT_AGGREGATOR)
  const [learningRate, setLearningRate] = useState(TRAINING_DEFAULTS.learningRate)
  const [epochs, setEpochs] = useState(TRAINING_DEFAULTS.epochs)
  const [trainBatchSize, setTrainBatchSize] = useState(TRAINING_DEFAULTS.batchSize)
  const [optimizer, setOptimizer] = useState(TRAINING_DEFAULTS.optimizer)
  const [earlyStoppingPatience, setEarlyStoppingPatience] = useState(TRAINING_DEFAULTS.earlyStoppingPatience)
  const [autoBalance, setAutoBalance] = useState(TRAINING_DEFAULTS.autoBalance)

  // Split config
  const [splitStrategy, setSplitStrategy] = useState<SplitStrategy>(SPLIT_DEFAULTS.strategy)
  const [kFoldSplits, setKFoldSplits] = useState(SPLIT_DEFAULTS.kFoldSplits)
  const [randomSeed, setRandomSeed] = useState(SPLIT_DEFAULTS.randomSeed)

  return {
    // Preprocessing
    tileSize,
    setTileSize,
    stride,
    setStride,
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

    // Split config
    splitStrategy,
    setSplitStrategy,
    kFoldSplits,
    setKFoldSplits,
    randomSeed,
    setRandomSeed,
  }
}

