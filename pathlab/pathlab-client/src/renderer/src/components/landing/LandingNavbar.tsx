import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { LanguageSwitcher } from '../common/LanguageSwitcher'
import { Button } from '../ui/button'
import { LANDING_NAV_ITEMS } from '../../data/landing/landing-nav'

export function LandingNavbar({ onLogin }: { onLogin: () => void }) {
  const { t } = useTranslation()
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20)
    }
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  return (
    <nav
      className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-white/80 backdrop-blur-md border-b shadow-sm py-3 border-[color:var(--landing-border)]'
          : 'bg-transparent py-5'
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <img src="/images/pathlab-logo.png" alt="PathLab" className="h-8 w-auto" />
        </div>
        
        <div className="hidden lg:flex items-center gap-8">
          {LANDING_NAV_ITEMS.map((item: { labelKey: string; href: string }) => (
            <a
              key={item.labelKey}
              href={item.href}
              className="text-sm font-medium text-[color:var(--landing-text-secondary)] hover:text-[color:var(--landing-primary)] transition-colors"
            >
              {t(item.labelKey)}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-4">
          <LanguageSwitcher />
          <Button
            onClick={onLogin}
            className="hidden sm:flex bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] text-white shadow-md rounded-full px-6"
          >
            {t('landing.nav.getStarted', 'Get Started')}
          </Button>
        </div>
      </div>
    </nav>
  )
}
