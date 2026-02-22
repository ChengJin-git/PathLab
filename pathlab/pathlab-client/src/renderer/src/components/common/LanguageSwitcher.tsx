import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe, Check } from 'lucide-react'
import { supportedLanguages, changeLanguage, SupportedLanguage } from '../../i18n'

interface LanguageSwitcherProps {
  className?: string
  variant?: 'dropdown' | 'inline' | 'icon'
}

export function LanguageSwitcher({ className, variant = 'dropdown' }: LanguageSwitcherProps) {
  const { i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  
  const currentLang = supportedLanguages.find(l => l.code === i18n.language) || supportedLanguages[0]
  
  const handleChange = (langCode: string) => {
    changeLanguage(langCode as SupportedLanguage)
    setOpen(false)
  }

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  if (variant === 'icon') {
    return (
      <div className={`relative ${className || ''}`} ref={containerRef}>
        <button
          onClick={() => setOpen(prev => !prev)}
          className="p-1.5 sm:p-2 text-gray-500 hover:text-primary-600 hover:bg-gray-100 rounded-lg transition-colors"
          title={currentLang.nativeName}
        >
          <Globe className="w-5 h-5" />
        </button>
        {open && (
          <div className="absolute right-0 top-full mt-1 min-w-[160px] bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50">
            {supportedLanguages.map((lang) => (
              <button
                key={lang.code}
                onClick={() => handleChange(lang.code)}
                className={`w-full text-left px-4 py-2 text-sm flex items-center justify-between gap-3 hover:bg-gray-50 transition-colors ${
                  lang.code === i18n.language ? 'text-primary-600 font-medium' : 'text-gray-700'
                }`}
              >
                <span className="whitespace-nowrap">{lang.nativeName}</span>
                {lang.code === i18n.language && <Check className="w-4 h-4 flex-shrink-0" />}
              </button>
            ))}
          </div>
        )}
      </div>
    )
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
