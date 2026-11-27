import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { LanguageSwitcher } from '../common/LanguageSwitcher'
import { LANDING_NAV_ITEMS } from '../../constants/landing/landing-nav'
import { Menu, X } from 'lucide-react'
import pathlabLogo from '../../../public/images/pathlab-logo.png'

export function LandingNavbar({ onLogin }: { onLogin: () => void }) {
  const { t } = useTranslation()
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const navRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 16)
    update()
    window.addEventListener('scroll', update, { passive: true })
    return () => window.removeEventListener('scroll', update)
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setMenuOpen(false); menuButton.current?.focus() }
    }
    const outside = (event: PointerEvent) => {
      if (!navRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const desktop = window.matchMedia('(min-width: 1024px)')
    const resize = () => { if (desktop.matches) setMenuOpen(false) }
    document.addEventListener('keydown', close)
    document.addEventListener('pointerdown', outside)
    desktop.addEventListener('change', resize)
    return () => { document.removeEventListener('keydown', close); document.removeEventListener('pointerdown', outside); desktop.removeEventListener('change', resize) }
  }, [menuOpen])

  return (
    <nav ref={navRef} className={`public-nav ${scrolled || menuOpen ? 'is-scrolled' : ''}`} aria-label={t('publicExperience.menu')}>
      <div className="public-container public-nav__bar">
        <Link to="/" className="public-nav__brand" aria-label="PathLab"><img src={pathlabLogo} alt="PathLab" width="998" height="250" /></Link>
        <div className="public-nav__links">{LANDING_NAV_ITEMS.map(item => <a key={item.labelKey} href={item.href}>{t(item.labelKey)}</a>)}</div>
        <div className="public-nav__actions"><LanguageSwitcher className="public-language" /><button type="button" className="public-button public-button--small" onClick={onLogin}>{t('common.signIn')}</button><button ref={menuButton} className="public-nav__menu" type="button" onClick={() => setMenuOpen(value => !value)} aria-expanded={menuOpen} aria-controls="public-mobile-nav" aria-label={t('publicExperience.menu')}>{menuOpen ? <X size={22} /> : <Menu size={22} />}</button></div>
      </div>
      {menuOpen && <div id="public-mobile-nav" className="public-nav__mobile">{LANDING_NAV_ITEMS.map(item => <a key={item.labelKey} href={item.href} onClick={() => setMenuOpen(false)}>{t(item.labelKey)}</a>)}</div>}
    </nav>
  )
}
