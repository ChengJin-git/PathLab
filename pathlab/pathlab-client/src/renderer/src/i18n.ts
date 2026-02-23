import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import enUS from './locales/en-US.json'
import zhCN from './locales/zh-CN.json'
import zhHK from './locales/zh-HK.json'

export const supportedLanguages = [
  { code: 'en-US', name: 'English', nativeName: 'English' },
  { code: 'zh-CN', name: 'Chinese (Simplified)', nativeName: '简体中文' },
  { code: 'zh-HK', name: 'Chinese (Traditional)', nativeName: '繁體中文' }
] as const

export type SupportedLanguage = typeof supportedLanguages[number]['code']

const getInitialLanguage = (): string => {
  const stored = localStorage.getItem('i18nextLng')
  if (stored && supportedLanguages.some(l => l.code === stored)) {
    return stored
  }

  const browserLang = navigator.language
  if (browserLang.startsWith('zh')) {
    if (browserLang.includes('HK') || browserLang.includes('TW')) {
      return 'zh-HK'
    }
    return 'zh-CN'
  }

  return 'en-US'
}

i18n
  .use(initReactI18next)
  .init({
    resources: {
      'en-US': { translation: enUS },
      'zh-CN': { translation: zhCN },
      'zh-HK': { translation: zhHK }
    },
    lng: getInitialLanguage(),
    fallbackLng: 'en-US',
    supportedLngs: ['en-US', 'zh-CN', 'zh-HK'],
    interpolation: {
      escapeValue: false
    }
  })

export const changeLanguage = (lang: SupportedLanguage) => {
  i18n.changeLanguage(lang)
  localStorage.setItem('i18nextLng', lang)
}

export default i18n
