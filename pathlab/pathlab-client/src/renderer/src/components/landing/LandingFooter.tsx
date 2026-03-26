import React from 'react'
import { useTranslation } from 'react-i18next'
import { LANDING_NAV_ITEMS } from '../../data/landing/landing-nav'

export function LandingFooter() {
  const { t } = useTranslation()

  return (
    <footer className="bg-white border-t border-[color:var(--landing-border)] py-12">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-12">
          <div className="col-span-1 md:col-span-2">
            <img src="/images/smartlab-logo.svg" alt="SmartLab" className="h-10 w-auto mb-4 opacity-80" />
            <p className="text-[color:var(--landing-text-secondary)] text-sm max-w-sm leading-relaxed">
              {t('landing.footer.description', 'Transforming pathology workflows with clinical-grade AI.')}
            </p>
          </div>
          <div>
            <h4 className="font-semibold text-[color:var(--landing-text-primary)] mb-4">{t('landing.footer.links', 'Links')}</h4>
            <ul className="space-y-3">
              {LANDING_NAV_ITEMS.map((item: { labelKey: string; href: string }) => (
                <li key={item.labelKey}>
                  <a href={item.href} className="text-sm text-[color:var(--landing-text-secondary)] hover:text-[color:var(--landing-primary)] transition-colors">
                    {t(item.labelKey)}
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="font-semibold text-[color:var(--landing-text-primary)] mb-4">{t('landing.footer.legal', 'Legal')}</h4>
            <ul className="space-y-3">
              <li><a href="/privacy" className="text-sm text-[color:var(--landing-text-secondary)] hover:text-[color:var(--landing-primary)] transition-colors">{t('landing.footer.privacy', 'Privacy Policy')}</a></li>
              <li><a href="/terms" className="text-sm text-[color:var(--landing-text-secondary)] hover:text-[color:var(--landing-primary)] transition-colors">{t('landing.footer.terms', 'Terms of Service')}</a></li>
            </ul>
          </div>
        </div>
        <div className="pt-8 border-t border-[color:var(--landing-border)] flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-sm text-[color:var(--landing-text-secondary)]">
            © 2026 SmartLab · {t('introduction.allRightsReserved', 'All Rights Reserved')}
          </p>
        </div>
      </div>
    </footer>
  )
}
