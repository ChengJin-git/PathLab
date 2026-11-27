import i18n, { type BackendModule } from 'i18next'
import { initReactI18next } from 'react-i18next'

export const supportedLanguages = [
  { code: 'en-US', name: 'English', nativeName: 'English' },
  { code: 'zh-CN', name: 'Chinese (Simplified)', nativeName: '简体中文' },
  { code: 'zh-HK', name: 'Chinese (Traditional)', nativeName: '繁體中文' }
] as const

export type SupportedLanguage = typeof supportedLanguages[number]['code']

type Bundle = Record<string, any>

function composeBundle(base: Bundle, research: Bundle, reports: Bundle, publicExperience: Bundle): Bundle {
  return { ...base, publicExperience, reports, autoResearch: { ...base.autoResearch, workbench: research } }
}

// Each language is a separate chunk: a page downloads only the language it shows.
// Locale files share one key set (see test/unit/i18n.test.ts), so no fallback language is loaded.
const bundleLoaders: Record<SupportedLanguage, () => Promise<Bundle>> = {
  'en-US': async () => {
    const [base, research, reports, publicExperience] = await Promise.all([
      import('./locales/en-US.json'), import('./locales/research'), import('./locales/reports'), import('./locales/publicExperience')
    ])
    return composeBundle(base.default, research.researchEn, reports.reportsEn, publicExperience.publicExperienceEn)
  },
  'zh-CN': async () => {
    const [base, research, reports, publicExperience] = await Promise.all([
      import('./locales/zh-CN.json'), import('./locales/research'), import('./locales/reports'), import('./locales/publicExperience')
    ])
    return composeBundle(base.default, research.researchZhCN, reports.reportsZhCN, publicExperience.publicExperienceZhCN)
  },
  'zh-HK': async () => {
    const [base, research, reports, publicExperience] = await Promise.all([
      import('./locales/zh-HK.json'), import('./locales/research'), import('./locales/reports'), import('./locales/publicExperience')
    ])
    return composeBundle(base.default, research.researchZhHK, reports.reportsZhHK, publicExperience.publicExperienceZhHK)
  }
}

export function isSupportedLanguage(code: string | null | undefined): code is SupportedLanguage {
  return supportedLanguages.some(l => l.code === code)
}

export function loadLanguageBundle(lang: SupportedLanguage): Promise<Bundle> {
  return bundleLoaders[lang]()
}

const lazyBundles: BackendModule = {
  type: 'backend',
  init() {},
  read(language, _namespace, callback) {
    if (!isSupportedLanguage(language)) {
      callback(null, {})
      return
    }
    loadLanguageBundle(language).then(bundle => callback(null, bundle), error => callback(error, null))
  }
}

const getInitialLanguage = (): SupportedLanguage => {
  const stored = localStorage.getItem('i18nextLng')
  if (isSupportedLanguage(stored)) return stored

  const browserLang = navigator.language
  if (browserLang.startsWith('zh')) {
    return browserLang.includes('HK') || browserLang.includes('TW') ? 'zh-HK' : 'zh-CN'
  }
  return 'en-US'
}

/** Resolves once the active language is loaded; render after it to avoid showing raw keys. */
export const i18nReady = i18n
  .use(lazyBundles)
  .use(initReactI18next)
  .init({
    lng: getInitialLanguage(),
    fallbackLng: false,
    supportedLngs: supportedLanguages.map(l => l.code),
    load: 'currentOnly',
    interpolation: {
      escapeValue: false
    }
  })

/** Loads the language bundle before switching, so the UI never renders untranslated keys. */
export async function changeLanguage(lang: SupportedLanguage): Promise<void> {
  await i18n.changeLanguage(lang)
  localStorage.setItem('i18nextLng', lang)
}

export default i18n
