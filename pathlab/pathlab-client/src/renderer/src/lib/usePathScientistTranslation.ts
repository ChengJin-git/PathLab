import { useTranslation } from 'react-i18next'

const PATHSCIENTIST_LANGUAGE = 'en-US'

/** PathScientist doctor workspace always renders in English. */
export function usePathScientistTranslation() {
  return useTranslation('translation', { lng: PATHSCIENTIST_LANGUAGE })
}
