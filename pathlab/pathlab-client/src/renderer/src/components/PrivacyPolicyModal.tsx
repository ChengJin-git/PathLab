import { ShieldCheck } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'

import { Button } from './ui/button'
import { getLegalInlineComponents } from './legal/LegalInlineLink'

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
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="p-6 border-b border-gray-100 bg-gray-50/60">
          <h3 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-emerald-600" />
            {t('privacyPolicy.title')}
          </h3>
        </div>

        <div className="p-6 max-h-[60vh] overflow-y-auto text-slate-600 space-y-6 text-sm leading-relaxed scrollbar-thin scrollbar-thumb-gray-200 scrollbar-track-transparent">
          <div className="text-center border-b border-gray-100 pb-4">
            <h2 className="text-xl font-bold text-slate-900">{t('privacyPolicy.fullTitle')}</h2>
            <div className="mt-2 text-xs text-slate-500 flex flex-col gap-1">
              <span>{t('privacyPolicy.operator')}</span>
              <span>{t('privacyPolicy.contact')}: <a href="mailto:cjinag@connect.ust.hk">cjinag@connect.ust.hk</a></span>
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

        <div className="p-6 bg-gray-50 flex justify-end gap-3 border-t border-gray-100">
          {onBackToTerms && (
            <Button variant="outline" onClick={onBackToTerms}>
              {t('privacyPolicy.backToTerms')}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
        </div>
      </div>
    </div>
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