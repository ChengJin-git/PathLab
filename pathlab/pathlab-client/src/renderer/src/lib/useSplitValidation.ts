/**
 * useSplitValidation Hook
 *
 * Handles data split validation logic for k-fold and random split strategies.
 */

import { useMemo } from 'react'
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
          message: 'No samples with survival data found. Please set event_time and event_status.',
        }
      }

      if (eventCount < 2 || censoredCount < 2) {
        const minCount = Math.min(eventCount, censoredCount)
        const missingType = eventCount < 2 ? 'Event (status=1)' : 'Censored (status=0)'
        return {
          isValid: false,
          maxK: 0,
          minSamplesPerClass: minCount,
          numClasses: 2,
          unlabeledCount,
          totalLabeled: totalWithSurvival,
          eventCount,
          censoredCount,
          message: `Each event_status needs at least 2 samples. ${missingType} has only ${minCount}.`,
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
          ? `Each event_status needs at least 2 samples. Current minimum: ${minSamplesPerStatus}.`
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
          ? 'No labeled samples found. Please assign labels to your slides.'
          : 'At least 2 classes are required for classification training.',
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
        ? `Each class needs at least 2 samples. Current minimum: ${minSamplesPerClass}.`
        : undefined,
    }
  }, [classDistribution, taskType])

  // Calculate validation for random 7:1:2 split
  const randomSplitValidation = useMemo((): RandomSplitValidation => {
    const isSurvival = taskType === 'survival'
    const minRequiredPerClass = 10

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
          message: 'No samples with survival data found.',
        }
      }

      if (eventCount === 0 || censoredCount === 0) {
        const missingType = eventCount === 0 ? 'Event (status=1)' : 'Censored (status=0)'
        return {
          isValid: false,
          minRequired: minRequiredPerClass * 2,
          minSamplesPerClass: minSamplesPerStatus,
          numClasses: 2,
          unlabeledCount,
          totalLabeled: totalWithSurvival,
          eventCount,
          censoredCount,
          message: `Both Event and Censored samples are required. ${missingType} has 0 samples.`,
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
          ? `Random split requires at least ${minRequiredPerClass} samples per event_status.`
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
          ? 'No labeled samples found.'
          : 'At least 2 classes are required.',
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
        ? `Random split requires at least ${minRequiredPerClass} samples per class.`
        : undefined,
    }
  }, [classDistribution, taskType])

  return {
    classDistribution,
    kFoldValidation,
    randomSplitValidation,
  }
}

