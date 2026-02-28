import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Shield, Loader2 } from 'lucide-react'
import { Button } from './ui/button'
import { getClientIP } from '../api'

interface DisclaimerModalProps {
  isOpen: boolean
  isLoading: boolean
  onAccept: () => void
  onDecline: () => void
}

export function DisclaimerModal({ isOpen, isLoading, onAccept, onDecline }: DisclaimerModalProps) {
  const { t } = useTranslation()
  const [clientIP, setClientIP] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      getClientIP().then(ip => setClientIP(ip))
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200">
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
            <strong>{t('disclaimer.scopeLabel')}:</strong> {t('disclaimer.scopeText')}
          </div>

          <div className="space-y-4">
            <TermsSection title={t('disclaimer.sections.s1.title')} items={[
              t('disclaimer.sections.s1.items.0'),
              t('disclaimer.sections.s1.items.1'),
              t('disclaimer.sections.s1.items.2')
            ]} />

            <TermsSection title={t('disclaimer.sections.s2.title')} items={[
              t('disclaimer.sections.s2.items.0'),
              t('disclaimer.sections.s2.items.1'),
              t('disclaimer.sections.s2.items.2')
            ]} />

            <TermsSection title={t('disclaimer.sections.s3.title')} items={[
              t('disclaimer.sections.s3.items.0'),
              t('disclaimer.sections.s3.items.1'),
              t('disclaimer.sections.s3.items.2'),
              t('disclaimer.sections.s3.items.3'),
              t('disclaimer.sections.s3.items.4'),
              t('disclaimer.sections.s3.items.5'),
              t('disclaimer.sections.s3.items.6'),
              t('disclaimer.sections.s3.items.7')
            ]} />

            <TermsSection title={t('disclaimer.sections.s4.title')} items={[
              t('disclaimer.sections.s4.items.0'),
              t('disclaimer.sections.s4.items.1'),
              t('disclaimer.sections.s4.items.2'),
              t('disclaimer.sections.s4.items.3')
            ]} />

            <TermsSection title={t('disclaimer.sections.s5.title')} items={[
              t('disclaimer.sections.s5.items.0'),
              t('disclaimer.sections.s5.items.1'),
              t('disclaimer.sections.s5.items.2'),
              t('disclaimer.sections.s5.items.3'),
              t('disclaimer.sections.s5.items.4')
            ]} />

            <TermsSection title={t('disclaimer.sections.s6.title')} items={[
              t('disclaimer.sections.s6.items.0'),
              t('disclaimer.sections.s6.items.1'),
              t('disclaimer.sections.s6.items.2')
            ]} />

            <TermsSection title={t('disclaimer.sections.s7.title')} items={[
              t('disclaimer.sections.s7.items.0'),
              t('disclaimer.sections.s7.items.1'),
              t('disclaimer.sections.s7.items.2'),
              t('disclaimer.sections.s7.items.3')
            ]} />

            <TermsSection title={t('disclaimer.sections.s8.title')} items={[
              t('disclaimer.sections.s8.items.0'),
              t('disclaimer.sections.s8.items.1'),
              t('disclaimer.sections.s8.items.2')
            ]} />

            <section>
              <h4 className="font-bold text-slate-800 mb-1">{t('disclaimer.sections.s9.title')}</h4>
              <ul className="list-disc pl-5 space-y-1 text-xs">
                <li>{t('disclaimer.sections.s9.items.0')}
                  <ul className="list-[circle] pl-5 mt-1">
                    <li>{t('disclaimer.sections.s9.subItems.0')}</li>
                    <li>{t('disclaimer.sections.s9.subItems.1')}</li>
                    <li>{t('disclaimer.sections.s9.subItems.2')}</li>
                    <li>{t('disclaimer.sections.s9.subItems.3')}</li>
                    <li>{t('disclaimer.sections.s9.subItems.4')}</li>
                  </ul>
                </li>
                <li>{t('disclaimer.sections.s9.items.1')}</li>
              </ul>
            </section>

            <TermsSection title={t('disclaimer.sections.s10.title')} items={[
              t('disclaimer.sections.s10.items.0'),
              t('disclaimer.sections.s10.items.1')
            ]} />

            <TermsSection title={t('disclaimer.sections.s11.title')} items={[
              t('disclaimer.sections.s11.items.0'),
              t('disclaimer.sections.s11.items.1')
            ]} />

            <TermsSection title={t('disclaimer.sections.s12.title')} items={[
              t('disclaimer.sections.s12.items.0'),
              t('disclaimer.sections.s12.items.1')
            ]} />

            <TermsSection title={t('disclaimer.sections.s13.title')} items={[
              t('disclaimer.sections.s13.items.0'),
              t('disclaimer.sections.s13.items.1'),
              t('disclaimer.sections.s13.items.2')
            ]} />

            <TermsSection title={t('disclaimer.sections.s14.title')} items={[
              t('disclaimer.sections.s14.items.0'),
              t('disclaimer.sections.s14.items.1'),
              t('disclaimer.sections.s14.items.2')
            ]} />

            <TermsSection title={t('disclaimer.sections.s15.title')} items={[
              t('disclaimer.sections.s15.items.0'),
              t('disclaimer.sections.s15.items.1'),
              t('disclaimer.sections.s15.items.2')
            ]} />

            <TermsSection title={t('disclaimer.sections.s16.title')} items={[
              t('disclaimer.sections.s16.items.0'),
              t('disclaimer.sections.s16.items.1'),
              t('disclaimer.sections.s16.items.2')
            ]} />

            <section>
              <h4 className="font-bold text-slate-800 mb-1">{t('disclaimer.sections.s17.title')}</h4>
              <p className="text-xs">
                {t('disclaimer.sections.s17.content')}
              </p>
            </section>

            <section>
              <h4 className="font-bold text-slate-800 mb-1">{t('disclaimer.sections.s18.title')}</h4>
              <ul className="list-disc pl-5 space-y-1 text-xs">
                <li>{t('disclaimer.sections.s18.items.0')}
                  <ul className="list-[circle] pl-5 mt-1">
                    <li>{t('disclaimer.sections.s18.subItems.0')}</li>
                    <li>{t('disclaimer.sections.s18.subItems.1')}</li>
                    <li>{t('disclaimer.sections.s18.subItems.2')}</li>
                    <li>{t('disclaimer.sections.s18.subItems.3')}</li>
                  </ul>
                </li>
                <li>{t('disclaimer.sections.s18.items.1')}</li>
              </ul>
            </section>

            <TermsSection title={t('disclaimer.sections.s19.title')} items={[
              t('disclaimer.sections.s19.items.0'),
              t('disclaimer.sections.s19.items.1')
            ]} />

            <TermsSection title={t('disclaimer.sections.s20.title')} items={[
              t('disclaimer.sections.s20.items.0'),
              t('disclaimer.sections.s20.items.1'),
              t('disclaimer.sections.s20.items.2')
            ]} />

            <TermsSection title={t('disclaimer.sections.s21.title')} items={[
              t('disclaimer.sections.s21.items.0'),
              t('disclaimer.sections.s21.items.1'),
              t('disclaimer.sections.s21.items.2'),
              t('disclaimer.sections.s21.items.3')
            ]} />

            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-amber-900 text-xs">
              <strong>{t('disclaimer.important')}:</strong> {t('disclaimer.importantText')}
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
        </div>
      </div>
    </div>
  )
}

function TermsSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h4 className="font-bold text-slate-800 mb-1">{title}</h4>
      <ul className="list-disc pl-5 space-y-1 text-xs">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </section>
  )
}
