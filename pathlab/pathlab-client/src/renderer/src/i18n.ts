import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import enUS from './locales/en-US.json'
import zhCN from './locales/zh-CN.json'
import zhHK from './locales/zh-HK.json'

import drEnUS from './lib/deep-research/en.json'
import drZhCN from './lib/deep-research/zh-CN.json'
import drZhHK from './lib/deep-research/zh-HK.json'

function deepMerge(target: any, source: any): any {
  if (typeof target !== 'object' || target === null || Array.isArray(target)) return source;
  if (typeof source !== 'object' || source === null || Array.isArray(source)) return source;

  const result = { ...target };
  for (const key of Object.keys(source)) {
    if (key in target) {
      result[key] = deepMerge(target[key], source[key]);
    } else {
      result[key] = source[key];
    }
  }
  return result;
}

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

export const getDeepResearchLocale = (
  language: string = i18n.resolvedLanguage || i18n.language || getInitialLanguage()
): 'zh-CN' | 'en-US' => {
  return language.startsWith('en') ? 'en-US' : 'zh-CN'
}

i18n
  .use(initReactI18next)
  .init({
    resources: {
      // Keep deep-research-only keys, but let the main app locales remain the
      // source of truth for any overlapping translations.
      'en-US': { translation: deepMerge(drEnUS, enUS) },
      'zh-CN': { translation: deepMerge(drZhCN, zhCN) },
      'zh-HK': { translation: deepMerge(drZhHK, zhHK) }
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
