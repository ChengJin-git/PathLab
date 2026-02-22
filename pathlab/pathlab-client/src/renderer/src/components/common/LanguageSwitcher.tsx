import { useTranslation } from 'react-i18next'
import { Globe } from 'lucide-react'
import { supportedLanguages, changeLanguage, SupportedLanguage } from '../../i18n'

interface LanguageSwitcherProps {
  className?: string
  variant?: 'dropdown' | 'inline'
}

export function LanguageSwitcher({ className, variant = 'dropdown' }: LanguageSwitcherProps) {
  const { i18n } = useTranslation()
  
  const currentLang = supportedLanguages.find(l => l.code === i18n.language) || supportedLanguages[0]
  
  const handleChange = (langCode: string) => {
    changeLanguage(langCode as SupportedLanguage)
  }

  if (variant === 'inline') {
    return (
      <div className={`flex items-center gap-2 ${className || ''}`}>
        <Globe className="w-4 h-4 text-gray-500" />
        <select
          value={i18n.language}
          onChange={(e) => handleChange(e.target.value)}
          className="bg-transparent border-none text-sm text-gray-700 focus:outline-none focus:ring-0 cursor-pointer"
        >
          {supportedLanguages.map((lang) => (
            <option key={lang.code} value={lang.code}>
              {lang.nativeName}
            </option>
          ))}
        </select>
      </div>
    )
  }

  return (
    <div className={`relative ${className || ''}`}>
      <select
        value={i18n.language}
        onChange={(e) => handleChange(e.target.value)}
        className="appearance-none bg-white border border-gray-200 rounded-lg px-3 py-1.5 pr-8 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-100 focus:border-primary-300 cursor-pointer hover:bg-gray-50 transition-colors"
      >
        {supportedLanguages.map((lang) => (
          <option key={lang.code} value={lang.code}>
            {lang.nativeName}
          </option>
        ))}
      </select>
      <Globe className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
    </div>
  )
}
