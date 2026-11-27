import { Trans, useTranslation } from 'react-i18next'

import { Button } from './ui/button'
import { getLegalInlineComponents } from './legal/LegalInlineLink'
import { LegalDialog } from './legal/LegalDialog'
import { InstallationContact } from './legal/InstallationContact'

interface PrivacyPolicyModalProps {
  isOpen: boolean
  onClose: () => void
  onBackToTerms?: () => void
}

interface PrivacySectionData {
  title: string
  items?: string[]
  content?: string
}

const PRIVACY_SECTION_KEYS = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'] as const

export function PrivacyPolicyModal({ isOpen, onClose, onBackToTerms }: PrivacyPolicyModalProps) {
  const { t, i18n } = useTranslation()
  const sections = PRIVACY_SECTION_KEYS.map((key) =>
    t(`privacyPolicy.sections.${key}`, { returnObjects: true }) as PrivacySectionData
  )
  const legalComponents = getLegalInlineComponents(i18n.language)

  if (!isOpen) return null

  return (
    <LegalDialog open={isOpen} onClose={onClose} title={t('privacyPolicy.title')}>
        <div className="legal-dialog-body text-slate-600 space-y-6">
          <div className="text-center border-b border-gray-100 pb-4">
            <h2 className="text-xl font-bold text-slate-900">{t('privacyPolicy.fullTitle')}</h2>
            <div className="legal-dialog-meta mt-2 flex flex-col gap-1">
              <span>{t('privacyPolicy.revision')}</span>
              <span>{t('privacyPolicy.contact')}: <InstallationContact /></span>
            </div>
          </div>

          <div className="bg-emerald-50 border border-emerald-100 rounded-lg p-4 text-emerald-900 text-xs italic">
            <strong>{t('privacyPolicy.introLabel')}:</strong>{' '}
            <Trans i18nKey="privacyPolicy.introText" components={legalComponents} />
          </div>

          <div className="space-y-4">
            {sections.map((section, index) => (
              <PrivacySection
                key={PRIVACY_SECTION_KEYS[index]}
                sectionKey={PRIVACY_SECTION_KEYS[index]}
                title={section.title}
                items={section.items}
                content={section.content}
                legalComponents={legalComponents}
              />
            ))}

            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-amber-900 text-xs">
              <strong>{t('privacyPolicy.important')}:</strong>{' '}
              <Trans i18nKey="privacyPolicy.importantText" components={legalComponents} />
            </div>
          </div>
        </div>

        <div className="legal-dialog-footer">
          {onBackToTerms && (
            <Button variant="outline" onClick={onBackToTerms}>
              {t('privacyPolicy.backToTerms')}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
        </div>
    </LegalDialog>
  )
}

function PrivacySection({
  sectionKey,
  title,
  items,
  content,
  legalComponents,
}: PrivacySectionData & {
  sectionKey: string
  legalComponents: ReturnType<typeof getLegalInlineComponents>
}) {
  return (
    <section>
      <h4 className="font-bold text-slate-800 mb-1">{title}</h4>
      {content ? (
        <p className="text-xs">
          <Trans i18nKey={`privacyPolicy.sections.${sectionKey}.content`} components={legalComponents} />
        </p>
      ) : (
        <ul className="list-disc pl-5 space-y-1 text-xs">
          {(items ?? []).map((_, index) => (
            <li key={index}>
              <Trans i18nKey={`privacyPolicy.sections.${sectionKey}.items.${index}`} components={legalComponents} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
