import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Shield, Loader2 } from 'lucide-react'
import { Button } from './ui/button'
import { getClientIP } from '../api/users'
import { getLegalInlineComponents } from './legal/LegalInlineLink'
import { ModalShell } from './ui/modal-shell'

interface DisclaimerModalProps {
  isOpen: boolean
  isLoading: boolean
  onAccept: () => void
  onDecline: () => void
  previewOnly?: boolean
  onClose?: () => void
  onOpenPrivacyPolicy?: () => void
}

interface DisclaimerSectionData {
  title: string
  items?: string[]
  subItems?: string[]
  content?: string
}

const DISCLAIMER_SECTION_KEYS = [
  's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10', 's11',
  's12', 's13', 's14', 's15', 's16', 's17', 's18', 's19', 's20', 's21'
] as const

export function DisclaimerModal({
  isOpen,
  isLoading,
  onAccept,
  onDecline,
  previewOnly = false,
  onClose,
  onOpenPrivacyPolicy,
}: DisclaimerModalProps) {
  const { t, i18n } = useTranslation()
  const [clientIP, setClientIP] = useState<string | null>(null)
  const sections = DISCLAIMER_SECTION_KEYS.map((key) =>
    t(`disclaimer.sections.${key}`, { returnObjects: true }) as DisclaimerSectionData
  )
  const legalComponents = getLegalInlineComponents(i18n.language)

  useEffect(() => {
    if (isOpen) {
      getClientIP().then(ip => setClientIP(ip))
    }
  }, [isOpen])

  return (
    <ModalShell isOpen={isOpen} maxWidth="xl" className="max-w-4xl">
        <div className="p-6 border-b border-gray-100 bg-gray-50/50">
          <h3 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            <Shield className="w-5 h-5 text-blue-600" />
            {t('disclaimer.title')}
          </h3>
        </div>
        <div className="p-6 max-h-[60vh] overflow-y-auto text-slate-600 space-y-6 text-sm leading-relaxed scrollbar-thin scrollbar-thumb-gray-200 scrollbar-track-transparent">
          <div className="text-center border-b border-gray-100 pb-4">
            <h2 className="text-xl font-bold text-slate-900">{t('disclaimer.fullTitle')}</h2>
            <div className="mt-2 text-xs text-slate-500 flex flex-col gap-1">
              <span>{t('disclaimer.operator')}</span>
              <span>{t('disclaimer.contact')}: <a href="mailto:cjinag@connect.ust.hk">cjinag@connect.ust.hk</a></span>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 text-blue-900 text-xs italic">
            <strong>{t('disclaimer.scopeLabel')}:</strong>{' '}
            <Trans i18nKey="disclaimer.scopeText" components={legalComponents} />
          </div>

          {onOpenPrivacyPolicy && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-xs text-emerald-900 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <strong>{t('disclaimer.privacyNoticeTitle')}:</strong>{' '}
                <Trans i18nKey="disclaimer.privacyNoticeText" components={legalComponents} />
              </div>
              <Button variant="outline" onClick={onOpenPrivacyPolicy} className="border-emerald-300 text-emerald-800 hover:bg-emerald-100">
                {t('disclaimer.viewPrivacyPolicy')}
              </Button>
            </div>
          )}

          <div className="space-y-4">
            {sections.map((section, index) => (
              <TermsSection
                key={DISCLAIMER_SECTION_KEYS[index]}
                sectionKey={DISCLAIMER_SECTION_KEYS[index]}
                title={section.title}
                items={section.items}
                subItems={section.subItems}
                content={section.content}
                legalComponents={legalComponents}
              />
            ))}

            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-amber-900 text-xs">
              <strong>{t('disclaimer.important')}:</strong>{' '}
              <Trans i18nKey="disclaimer.importantText" components={legalComponents} />
            </div>

            <div className="text-center text-slate-600 text-sm font-medium pt-4 border-t border-gray-100">
              {clientIP && (
                <p className="text-xs text-slate-500">
                  {t('disclaimer.yourIpAddress')}: {clientIP}
                </p>
              )}
            </div>
          </div>
        </div>
        <div className="p-6 bg-gray-50 flex justify-end gap-3 border-t border-gray-100">
          {onOpenPrivacyPolicy && (
            <Button variant="outline" onClick={onOpenPrivacyPolicy} disabled={isLoading}>
              {t('disclaimer.viewPrivacyPolicy')}
            </Button>
          )}
          {previewOnly ? (
            <Button
              variant="ghost"
              onClick={onClose ?? onDecline}
              className="text-slate-600 hover:text-slate-900 hover:bg-slate-200"
            >
              {t('common.close')}
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                onClick={onDecline}
                disabled={isLoading}
                className="text-slate-600 hover:text-slate-900 hover:bg-slate-200"
              >
                {t('disclaimer.cancel')}
              </Button>
              <Button
                onClick={onAccept}
                disabled={isLoading}
                className="bg-blue-600 hover:bg-blue-700 text-white shadow-md hover:shadow-lg transition-all"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    {t('disclaimer.processing')}
                  </>
                ) : (
                  t('disclaimer.agreeAndContinue')
                )}
              </Button>
            </>
          )}
        </div>
    </ModalShell>
  )
}

function TermsSection({
  sectionKey,
  title,
  items,
  subItems,
  content,
  legalComponents,
}: {
  sectionKey: string
  title: string
  items?: string[]
  subItems?: string[]
  content?: string
  legalComponents: ReturnType<typeof getLegalInlineComponents>
}) {
  return (
    <section>
      <h4 className="font-bold text-slate-800 mb-1">{title}</h4>
      {content ? (
        <p className="text-xs">
          <Trans i18nKey={`disclaimer.sections.${sectionKey}.content`} components={legalComponents} />
        </p>
      ) : (
        <ul className="list-disc pl-5 space-y-1 text-xs">
          {(items ?? []).map((_, index) => (
            <li key={index}>
              <Trans i18nKey={`disclaimer.sections.${sectionKey}.items.${index}`} components={legalComponents} />
              {index === 0 && (subItems?.length ?? 0) > 0 && (
                <ul className="list-[circle] pl-5 mt-1">
                  {subItems?.map((_, subIndex) => (
                    <li key={subIndex}>
                      <Trans i18nKey={`disclaimer.sections.${sectionKey}.subItems.${subIndex}`} components={legalComponents} />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
