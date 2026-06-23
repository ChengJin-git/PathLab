import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LANDING_NAV_ITEMS } from '../../constants/landing/landing-nav'
import { DisclaimerModal } from '../DisclaimerModal'
import { PrivacyPolicyModal } from '../PrivacyPolicyModal'

export function LandingFooter() {
  const { t } = useTranslation()
  const [showTerms, setShowTerms] = useState(false)
  const [showPrivacy, setShowPrivacy] = useState(false)

  return (
    <footer className="bg-white border-t border-[color:var(--landing-border)] py-12">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-12">
          <div className="col-span-1 md:col-span-2">
            <img src="/images/smartxlab-logo.png" alt="SmartXLab" className="mb-5 h-14 sm:h-16 w-auto opacity-85" />
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
              <li><button type="button" onClick={() => setShowPrivacy(true)} className="text-sm text-[color:var(--landing-text-secondary)] hover:text-[color:var(--landing-primary)] transition-colors cursor-pointer">{t('landing.footer.privacy', 'Privacy Policy')}</button></li>
              <li><button type="button" onClick={() => setShowTerms(true)} className="text-sm text-[color:var(--landing-text-secondary)] hover:text-[color:var(--landing-primary)] transition-colors cursor-pointer">{t('landing.footer.terms', 'Terms of Service')}</button></li>
            </ul>
          </div>
        </div>
        <div className="pt-8 border-t border-[color:var(--landing-border)] flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-sm text-[color:var(--landing-text-secondary)]">
            © 2026 SmartXLab · {t('introduction.allRightsReserved', 'All Rights Reserved')}
          </p>
        </div>
      </div>
      <DisclaimerModal
        isOpen={showTerms}
        isLoading={false}
        previewOnly
        onAccept={() => {}}
        onDecline={() => setShowTerms(false)}
        onClose={() => setShowTerms(false)}
        onOpenPrivacyPolicy={() => { setShowTerms(false); setShowPrivacy(true) }}
      />
      <PrivacyPolicyModal
        isOpen={showPrivacy}
        onClose={() => setShowPrivacy(false)}
        onBackToTerms={() => { setShowPrivacy(false); setShowTerms(true) }}
      />
    </footer>
  )
}
