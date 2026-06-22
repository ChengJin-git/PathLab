import { DEFAULT_FEATURE_BATCH_SIZE } from '../constants/training'
import { getQueueStatus, type QueueStatus } from '../api/queue'

const FEATURE_BATCH_SIZE_CANDIDATES = [64, 32, 16, 8, 4, 2, 1] as const
const DEFAULT_MODEL_VRAM_MB = 1000
const MIN_INFERENCE_OVERHEAD_MB = 500
const BATCH_BUFFER_MB = 768
const UNKNOWN_VRAM_FALLBACK_BATCH_SIZE = 16

const MODEL_SIZE_ESTIMATES_MB: Record<string, number> = {
  resnet50: 200,
  plip: 400,
  patho_clip: 400,
  conch: 600,
  phikon: 800,
  vit_l_16: 1200,
  uni: 1500,
  mstar: 1500,
  gpfm: 1500,
  phikon2: 1800,
  virchow: 3000,
  virchow2: 3000,
  conch15: 3000,
  'h-optimus-0': 4000,
  uni2: 5000,
  openmidnight: 5500,
  'h-optimus-1': 6000,
}

export function getFeatureBatchSizeForAvailableVram(
  featureExtractor: string | undefined,
  availableVramMb: number | undefined,
): number {
  if (!availableVramMb || !Number.isFinite(availableVramMb) || availableVramMb <= 0) {
    return UNKNOWN_VRAM_FALLBACK_BATCH_SIZE
  }

  const modelSizeMb = MODEL_SIZE_ESTIMATES_MB[String(featureExtractor ?? '').trim().toLowerCase()] ?? DEFAULT_MODEL_VRAM_MB
  const budgetMb = Math.max(0, availableVramMb * 0.85 - modelSizeMb - MIN_INFERENCE_OVERHEAD_MB)
  const candidate = FEATURE_BATCH_SIZE_CANDIDATES.find((size) => size * BATCH_BUFFER_MB <= budgetMb)
  return candidate ?? 1
}

export function resolveFeatureBatchSizeForSubmission({
  configuredBatchSize,
  featureExtractor,
  queueStatus,
  treatDefaultAsUnset = false,
}: {
  configuredBatchSize: number | undefined
  featureExtractor: string | undefined
  queueStatus: QueueStatus | null | undefined
  treatDefaultAsUnset?: boolean
}): number {
  if (
    configuredBatchSize &&
    configuredBatchSize > 0 &&
    (!treatDefaultAsUnset || configuredBatchSize !== DEFAULT_FEATURE_BATCH_SIZE)
  ) {
    return configuredBatchSize
  }

  const freeVramMb = queueStatus?.gpus?.reduce<number | undefined>((best, gpu) => {
    if (!Number.isFinite(gpu.free_mb) || gpu.free_mb <= 0) return best
    return best === undefined ? gpu.free_mb : Math.max(best, gpu.free_mb)
  }, undefined)

  return getFeatureBatchSizeForAvailableVram(featureExtractor, freeVramMb)
}

export async function resolveFeatureBatchSizeForSubmissionFromQueue(
  configuredBatchSize: number | undefined,
  featureExtractor: string | undefined,
  options: { treatDefaultAsUnset?: boolean } = {},
): Promise<number> {
  if (
    configuredBatchSize &&
    configuredBatchSize > 0 &&
    (!options.treatDefaultAsUnset || configuredBatchSize !== DEFAULT_FEATURE_BATCH_SIZE)
  ) {
    return configuredBatchSize
  }

  try {
    const queueStatus = await getQueueStatus()
    return resolveFeatureBatchSizeForSubmission({
      configuredBatchSize,
      featureExtractor,
      queueStatus,
      treatDefaultAsUnset: options.treatDefaultAsUnset,
    })
  } catch (error) {
    console.warn('Falling back to conservative feature batch size after queue status lookup failed:', error)
    return UNKNOWN_VRAM_FALLBACK_BATCH_SIZE
  }
}
