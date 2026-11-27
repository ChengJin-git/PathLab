import { useTranslation } from 'react-i18next'
import type { ResearchCopy } from '../../locales/research'
import type { SupportedLanguage } from '../../i18n'

export function useResearchText() {
  const { t, i18n } = useTranslation()
  const text = t('autoResearch.workbench', { returnObjects: true }) as ResearchCopy
  const language: SupportedLanguage = i18n.language === 'zh-HK' ? 'zh-HK' : i18n.language.startsWith('zh') ? 'zh-CN' : 'en-US'
  return { text, language, status: (value: string) => text[value as keyof ResearchCopy] || value }
}
