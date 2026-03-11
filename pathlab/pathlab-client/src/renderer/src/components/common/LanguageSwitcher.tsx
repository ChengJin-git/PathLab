import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe, Check } from 'lucide-react'
import { supportedLanguages, changeLanguage, SupportedLanguage } from '../../i18n'
import { Select } from '../ui/select'

interface LanguageSwitcherProps {
  className?: string
  variant?: 'dropdown' | 'inline' | 'icon'
}

export function LanguageSwitcher({ className, variant = 'dropdown' }: LanguageSwitcherProps) {
  const { i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  
  const currentLang = supportedLanguages.find(l => l.code === i18n.language) || supportedLanguages[0]
  const options = supportedLanguages.map((lang) => ({ value: lang.code, label: lang.nativeName }))
  
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
    <div className={`relative w-[152px] ${className || ''}`}>
      <Globe className="pointer-events-none absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <Select
        value={currentLang.code}
        onChange={handleChange}
        options={options}
        triggerClassName="h-11 rounded-xl border-slate-200/90 bg-white/95 pl-9 pr-3 text-sm font-medium text-slate-700 shadow-md shadow-slate-200/60 backdrop-blur-sm hover:bg-white"
        dropdownClassName="rounded-xl border-slate-200 p-1.5 shadow-xl shadow-slate-200/70"
      />
    </div>
  )
}
