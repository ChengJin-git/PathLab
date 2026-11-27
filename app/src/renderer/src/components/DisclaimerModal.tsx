import { Trans, useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { Button } from './ui/button'
import { getLegalInlineComponents } from './legal/LegalInlineLink'
import { LegalDialog } from './legal/LegalDialog'
import { InstallationContact } from './legal/InstallationContact'

interface DisclaimerModalProps {
  isOpen: boolean
  isLoading: boolean
  onAccept: () => void
  onDecline: () => void
  previewOnly?: boolean
  onClose?: () => void
  onOpenPrivacyPolicy?: () => void
  error?: string | null
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
  error,
}: DisclaimerModalProps) {
  const { t, i18n } = useTranslation()
  const sections = DISCLAIMER_SECTION_KEYS.map((key) =>
    t(`disclaimer.sections.${key}`, { returnObjects: true }) as DisclaimerSectionData
  )
  const legalComponents = getLegalInlineComponents(i18n.language)

  return (
    <LegalDialog open={isOpen} onClose={onClose ?? onDecline} title={t('disclaimer.title')} dismissible={previewOnly && !isLoading}>
        <div className="legal-dialog-body text-slate-600 space-y-6">
          <div className="text-center border-b border-gray-100 pb-4">
            <h2 className="text-xl font-bold text-slate-900">{t('disclaimer.fullTitle')}</h2>
            <div className="legal-dialog-meta mt-2 flex flex-col gap-1">
              <span>{t('disclaimer.revision')}</span>
              <span>{t('disclaimer.contact')}: <InstallationContact /></span>
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

          </div>
        </div>
        <div className="legal-dialog-footer">
          {error && <p role="alert" className="w-full text-sm text-red-700">{error}</p>}
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
    </LegalDialog>
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
