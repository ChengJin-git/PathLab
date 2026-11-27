import type { TFunction } from 'i18next'

/** Display terminology only; API data-type identifiers remain wsi / patch. */
export function dataTypeLabel(t: TFunction, type: string | null | undefined): string {
  switch (type?.toLowerCase()) {
    case 'wsi': return t('training.taskSetup.wholeSlides')
    case 'patch': return t('training.taskSetup.imagePatches')
    default: return type || '—'
  }
}
