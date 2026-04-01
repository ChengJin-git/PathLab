import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { LanguageSwitcher } from '../common/LanguageSwitcher'
import { Button } from '../ui/button'
import { LANDING_NAV_ITEMS } from '../../constants/landing/landing-nav'
import { Menu, X } from 'lucide-react'
import pathlabLogo from '../../../public/images/pathlab-logo.png'

export function LandingNavbar({ onLogin }: { onLogin: () => void }) {
  const { t } = useTranslation()
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

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
        scrolled || menuOpen
          ? 'bg-white/80 backdrop-blur-md border-b shadow-sm py-3 border-[color:var(--landing-border)]'
          : 'bg-transparent py-5'
      }`}
    >
      <div className="pt-safe" />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <img src={pathlabLogo} alt="PathLab" className="h-8 w-auto" />
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
          <button
            type="button"
            className="lg:hidden p-2 text-slate-600 hover:text-[color:var(--landing-primary)] transition-colors"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="Toggle menu"
          >
            {menuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
          
          <LanguageSwitcher />
          <Button
            onClick={onLogin}
            className="hidden sm:flex bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] text-white shadow-md rounded-full px-6"
          >
            {t('landing.nav.getStarted', 'Get Started')}
          </Button>
        </div>
      </div>

      {/* Mobile Menu */}
      <div 
        className={`lg:hidden overflow-hidden transition-all duration-300 ease-in-out bg-white/95 backdrop-blur-md border-b border-[color:var(--landing-border)] ${
          menuOpen ? 'max-h-screen opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="flex flex-col py-4 px-4 gap-2">
          {LANDING_NAV_ITEMS.map((item: { labelKey: string; href: string }) => (
            <a
              key={item.labelKey}
              href={item.href}
              className="py-3 px-6 text-base font-medium text-[color:var(--landing-text-secondary)] hover:bg-slate-50 hover:text-[color:var(--landing-primary)] rounded-lg transition-colors"
              onClick={() => setMenuOpen(false)}
            >
              {t(item.labelKey)}
            </a>
          ))}
          <div className="mt-4 px-6 pb-2">
            <Button
              onClick={() => {
                onLogin()
                setMenuOpen(false)
              }}
              className="w-full bg-[color:var(--landing-primary)] hover:bg-[color:var(--landing-primary-deep)] text-white shadow-md rounded-full h-12 text-base"
            >
              {t('landing.nav.getStarted', 'Get Started')}
            </Button>
          </div>
        </div>
      </div>
    </nav>
  )
}
