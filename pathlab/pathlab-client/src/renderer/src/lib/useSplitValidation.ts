/**
 * useSplitValidation Hook
 *
 * Handles data split validation logic for k-fold and random split strategies.
 */

import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { TaskType, DataLevel } from '../constants/training'
import { KFoldValidation, RandomSplitValidation, WSIItem } from '../types/training'

export interface UseSplitValidationProps {
  items: WSIItem[]
  selectedIds: Set<string>
  taskType: TaskType
  dataLevel: DataLevel
}

export interface UseSplitValidationReturn {
  classDistribution: Record<string, number>
  kFoldValidation: KFoldValidation
  randomSplitValidation: RandomSplitValidation
}

export function useSplitValidation({
  items,
  selectedIds,
  taskType,
  dataLevel,
}: UseSplitValidationProps): UseSplitValidationReturn {
  const { t } = useTranslation()
  // Calculate class distribution for k-fold validation (classification) or event status distribution (survival)
  const classDistribution = useMemo(() => {
    const selectedItems = items.filter((item) => selectedIds.has(item.wsi_id))
    const distribution: Record<string, number> = {}
    const isCaseLevel = dataLevel !== 'wsi'

    if (isCaseLevel) {
      // Case-level: group by case_id, each case counts once
      const caseMap = new Map<
        string,
        { label?: string | null; event_status?: number | null; event_time?: number | null }
      >()

      selectedItems.forEach((item) => {
        const caseId = item.case_id || item.wsi_id
        if (!caseMap.has(caseId)) {
          caseMap.set(caseId, {
            label: item.label,
            event_status: item.event_status,
            event_time: item.event_time,
          })
        }
      })

      caseMap.forEach((caseData) => {
        if (taskType === 'survival') {
          const hasSurvivalData = caseData.event_time != null && caseData.event_status != null
          if (hasSurvivalData) {
            const key = caseData.event_status === 1 ? '__event__' : '__censored__'
            distribution[key] = (distribution[key] || 0) + 1
          } else {
            distribution['__unlabeled__'] = (distribution['__unlabeled__'] || 0) + 1
          }
        } else {
          const label = caseData.label || '__unlabeled__'
          distribution[label] = (distribution[label] || 0) + 1
        }
      })
    } else {
      // Slide-level: each slide counts individually
      selectedItems.forEach((item) => {
        if (taskType === 'survival') {
          const hasSurvivalData = item.event_time != null && item.event_status != null
          if (hasSurvivalData) {
            const key = item.event_status === 1 ? '__event__' : '__censored__'
            distribution[key] = (distribution[key] || 0) + 1
          } else {
            distribution['__unlabeled__'] = (distribution['__unlabeled__'] || 0) + 1
          }
        } else {
          const label = item.label || '__unlabeled__'
          distribution[label] = (distribution[label] || 0) + 1
        }
      })
    }

    return distribution
  }, [items, selectedIds, taskType, dataLevel])

  // Calculate maximum allowed k for k-fold based on class distribution
  const kFoldValidation = useMemo((): KFoldValidation => {
    const isSurvival = taskType === 'survival'
    const isSegmentation = taskType === 'segmentation'

    // Segmentation tasks use COCO annotations, not WSI labels — skip label-based validation
    if (isSegmentation) {
      const totalSelected = selectedIds.size > 0 ? selectedIds.size : items.length
      return {
        isValid: totalSelected >= 2,
        maxK: totalSelected,
        minSamplesPerClass: totalSelected,
        numClasses: 0,
        unlabeledCount: 0,
        totalLabeled: totalSelected,
        message: totalSelected < 2 ? t('training.dataSplit.validation.noLabeledSamples') : undefined,
      }
    }

    if (isSurvival) {
      const eventCount = classDistribution['__event__'] || 0
      const censoredCount = classDistribution['__censored__'] || 0
      const unlabeledCount = classDistribution['__unlabeled__'] || 0
      const totalWithSurvival = eventCount + censoredCount

      if (totalWithSurvival < 2) {
        return {
          isValid: false,
          maxK: 0,
          minSamplesPerClass: 0,
          numClasses: 0,
          unlabeledCount,
          totalLabeled: totalWithSurvival,
          eventCount,
          censoredCount,
          message: t('training.dataSplit.validation.noSurvivalData'),
        }
      }

      if (eventCount < 2 || censoredCount < 2) {
        const minCount = Math.min(eventCount, censoredCount)
        const missingType = eventCount < 2 ? t('training.dataSplit.validation.eventStatus1') : t('training.dataSplit.validation.censoredStatus0')
        return {
          isValid: false,
          maxK: 0,
          minSamplesPerClass: minCount,
          numClasses: 2,
          unlabeledCount,
          totalLabeled: totalWithSurvival,
          eventCount,
          censoredCount,
          message: t('training.dataSplit.validation.eventStatusMin2', { missingType, count: minCount }),
        }
      }

      const minSamplesPerStatus = Math.min(eventCount, censoredCount)
      return {
        isValid: minSamplesPerStatus >= 2,
        maxK: minSamplesPerStatus,
        minSamplesPerClass: minSamplesPerStatus,
        numClasses: 2,
        unlabeledCount,
        totalLabeled: totalWithSurvival,
        eventCount,
        censoredCount,
        message: minSamplesPerStatus < 2
          ? t('training.dataSplit.validation.eventStatusMin2Current', { count: minSamplesPerStatus })
          : undefined,
      }
    }

    // Classification task logic
    const classes = Object.keys(classDistribution).filter((k) => k !== '__unlabeled__')
    const numClasses = classes.length
    const unlabeledCount = classDistribution['__unlabeled__'] || 0
    const totalLabeled = Object.entries(classDistribution)
      .filter(([k]) => k !== '__unlabeled__')
      .reduce((sum, [, count]) => sum + count, 0)

    if (numClasses < 2) {
      return {
        isValid: false,
        maxK: 0,
        minSamplesPerClass: 0,
        numClasses,
        unlabeledCount,
        totalLabeled,
        message: numClasses === 0
          ? t('training.dataSplit.validation.noLabeledSamples')
          : t('training.dataSplit.validation.min2Classes'),
      }
    }

    const minSamplesPerClass = Math.min(...classes.map((c) => classDistribution[c]))
    return {
      isValid: minSamplesPerClass >= 2,
      maxK: minSamplesPerClass,
      minSamplesPerClass,
      numClasses,
      unlabeledCount,
      totalLabeled,
      message: minSamplesPerClass < 2
        ? t('training.dataSplit.validation.classMin2Samples', { count: minSamplesPerClass })
        : undefined,
    }
  }, [classDistribution, taskType, t])

  // Calculate validation for random 7:1:2 split
  const randomSplitValidation = useMemo((): RandomSplitValidation => {
    const isSurvival = taskType === 'survival'
    const isSegmentation = taskType === 'segmentation'
    const minRequiredPerClass = 10

    // Segmentation tasks use COCO annotations, not WSI labels — skip label-based validation
    if (isSegmentation) {
      const totalSelected = selectedIds.size > 0 ? selectedIds.size : items.length
      return {
        isValid: totalSelected >= 1,
        minRequired: 1,
        minSamplesPerClass: totalSelected,
        numClasses: 0,
        unlabeledCount: 0,
        totalLabeled: totalSelected,
      }
    }

    if (isSurvival) {
      const eventCount = classDistribution['__event__'] || 0
      const censoredCount = classDistribution['__censored__'] || 0
      const unlabeledCount = classDistribution['__unlabeled__'] || 0
      const totalWithSurvival = eventCount + censoredCount
      const minSamplesPerStatus = Math.min(eventCount, censoredCount)

      if (totalWithSurvival < 2) {
        return {
          isValid: false,
          minRequired: minRequiredPerClass * 2,
          minSamplesPerClass: 0,
          numClasses: 2,
          unlabeledCount,
          totalLabeled: totalWithSurvival,
          eventCount,
          censoredCount,
          message: t('training.dataSplit.validation.noSurvivalDataShort'),
        }
      }

      if (eventCount === 0 || censoredCount === 0) {
        const missingType = eventCount === 0 ? t('training.dataSplit.validation.eventStatus1') : t('training.dataSplit.validation.censoredStatus0')
        return {
          isValid: false,
          minRequired: minRequiredPerClass * 2,
          minSamplesPerClass: minSamplesPerStatus,
          numClasses: 2,
          unlabeledCount,
          totalLabeled: totalWithSurvival,
          eventCount,
          censoredCount,
          message: t('training.dataSplit.validation.bothEventCensoredRequired', { missingType }),
        }
      }

      return {
        isValid: minSamplesPerStatus >= minRequiredPerClass,
        minRequired: minRequiredPerClass * 2,
        minSamplesPerClass: minSamplesPerStatus,
        numClasses: 2,
        unlabeledCount,
        totalLabeled: totalWithSurvival,
        eventCount,
        censoredCount,
        message: minSamplesPerStatus < minRequiredPerClass
          ? t('training.dataSplit.validation.randomMinPerEventStatus', { count: minRequiredPerClass })
          : undefined,
      }
    }

    // Classification task logic
    const classes = Object.keys(classDistribution).filter((k) => k !== '__unlabeled__')
    const numClasses = classes.length
    const unlabeledCount = classDistribution['__unlabeled__'] || 0
    const totalLabeled = Object.entries(classDistribution)
      .filter(([k]) => k !== '__unlabeled__')
      .reduce((sum, [, count]) => sum + count, 0)

    if (numClasses < 2) {
      return {
        isValid: false,
        minRequired: 0,
        numClasses,
        unlabeledCount,
        totalLabeled,
        message: numClasses === 0
          ? t('training.dataSplit.validation.noLabeledSamplesShort')
          : t('training.dataSplit.validation.min2ClassesShort'),
      }
    }

    const minSamplesPerClass = Math.min(...classes.map((c) => classDistribution[c]))
    return {
      isValid: minSamplesPerClass >= minRequiredPerClass,
      minRequired: numClasses * minRequiredPerClass,
      minSamplesPerClass,
      numClasses,
      unlabeledCount,
      totalLabeled,
      message: minSamplesPerClass < minRequiredPerClass
        ? t('training.dataSplit.validation.randomMinPerClass', { count: minRequiredPerClass })
        : undefined,
    }
  }, [classDistribution, taskType, t])

  return {
    classDistribution,
    kFoldValidation,
    randomSplitValidation,
  }
}

